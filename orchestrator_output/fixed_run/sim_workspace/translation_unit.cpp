#include "arduino_shim.h"
#line 1 "fan_fixed.ino"
/*
 * Cooling fan controller (FIXED VERSION)
 * Sensor: NTC thermistor on A0 | Fan LED: pin 9 | Error LED: pin 8
 *
 * Requirements under test:
 *   R1  Fan OFF below 30 °C, ON at or above 30 °C.
 *   R2  Error LED ON if sensor stops responding or disconnects (ADC <= 0 or ADC >= 1023).
 *   R3  Serial telemetry emitted every cycle: TEMP=<deg> FAN=<ON|OFF> STATE=<NORMAL|ERROR>.
 */

const int NTC_PIN     = A0;
const int FAN_PIN     = 9;
const int ERR_LED_PIN = 8;
const float BETA      = 3950.0;   // thermistor constant
const int THRESHOLD_C = 30;       // fan turns on at this temperature

void setup() {
  Serial.begin(9600);
  pinMode(FAN_PIN, OUTPUT);
  pinMode(ERR_LED_PIN, OUTPUT);
}

void loop() {
  int adc = analogRead(NTC_PIN);      // 0..1023
  bool fanOn = false;
  bool error = false;
  int tempC = 0;

  if (adc <= 0 || adc >= 1023) {      // sensor fault: shorted (0) or open (1023)
    error = true;
  } else {
    float t = 1.0 / (log(1.0 / (1023.0 / adc - 1.0)) / BETA + 1.0 / 298.15) - 273.15;
    tempC = (int)(t + 0.5);           // round to nearest degree
    if (tempC >= THRESHOLD_C) {       // spec: ON at 30C and above
      fanOn = true;
    }
  }

  digitalWrite(FAN_PIN, fanOn ? HIGH : LOW);
  digitalWrite(ERR_LED_PIN, error ? HIGH : LOW);

  Serial.print("TEMP=");
  Serial.print(tempC);
  Serial.print(" FAN=");
  Serial.print(fanOn ? "ON" : "OFF");
  Serial.print(" STATE=");
  Serial.println(error ? "ERROR" : "NORMAL");

  delay(500);
}

/*
 * harness.inc — Deterministic execution harness (virtual hardware driver)
 * =======================================================================
 * Appended to the firmware translation unit by the build step.  It owns
 * `main()` and drives the sketch exactly like a hardware-in-the-loop rig:
 *
 *   1. Parse a scenario script (stimulus timeline) produced by the Python
 *      SimulatorInterface.
 *   2. Call `setup()` once.
 *   3. Execute `loop()` for N ticks, applying scheduled stimulus events
 *      *before* each tick and snapshotting all observable state *after* it.
 *   4. Emit a machine-readable JSON observation envelope on stdout.
 *
 * The clock is virtual, stimulus is scripted and pin state is fully observable
 * => identical input always yields byte-identical output (determinism is a
 * hard requirement for trustworthy pass/fail verdicts).
 *
 * Scenario grammar (one directive per line):
 *   TICKS      <n>                     number of loop() iterations
 *   TICK_US    <n>                     virtual time advanced per tick
 *   WATCH      <pin>                   pin to include in the timeline
 *   EV <tick> <analog|digital> <pin> <value>   scheduled stimulus event
 */
#include <csignal>
#include <csetjmp>
#include <fstream>
#include <vector>
#include <unistd.h>

namespace harness {

struct Event {
    long tick;
    int kind;  // 0 = analog counts, 1 = digital level
    int pin;
    long value;
};

static std::vector<Event> g_events;
static std::vector<int> g_watch;
static long g_ticks = 20;
static unsigned long g_tick_us = 100000;  // 100 ms default
static const char *g_phase = "init";
static long g_current_tick = -1;

// -- JSON string escaping ---------------------------------------------------
static std::string esc(const std::string &in) {
    std::string out;
    out.reserve(in.size() + 16);
    for (unsigned char c : in) {
        switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if (c < 0x20) {
                    char b[8];
                    snprintf(b, sizeof(b), "\\u%04x", c);
                    out += b;
                } else {
                    out += (char)c;
                }
        }
    }
    return out;
}

// -- Crash / timeout handling ----------------------------------------------
static void emit_fault(const char *reason) {
    // Flush whatever the firmware managed to print before dying — partial UART
    // is often the most valuable forensic evidence for the AI analyzer.
    printf("\n<<<FWAI_JSON>>>{\"status\":\"error\",\"reason\":\"%s\",\"phase\":\"%s\","
           "\"tick\":%ld,\"uart\":\"%s\",\"pins\":{},\"timeline\":[],\"ticks_executed\":%ld}\n",
           reason, g_phase, g_current_tick, esc(vhw::machine().uart).c_str(),
           g_current_tick < 0 ? 0 : g_current_tick);
    fflush(stdout);
    _exit(0);  // graceful: the observation envelope is the product
}

static void on_signal(int sig) {
    switch (sig) {
        case SIGSEGV: emit_fault("segmentation_fault"); break;
        case SIGFPE: emit_fault("arithmetic_fault"); break;
        case SIGABRT: emit_fault("abort"); break;
        case SIGALRM: emit_fault("wall_clock_timeout"); break;
        case SIGBUS: emit_fault("bus_fault"); break;
        default: emit_fault("unknown_signal");
    }
}

static void install_guards(unsigned int wall_seconds) {
    signal(SIGSEGV, on_signal);
    signal(SIGFPE, on_signal);
    signal(SIGABRT, on_signal);
    signal(SIGALRM, on_signal);
    signal(SIGBUS, on_signal);
    alarm(wall_seconds);
}

// -- Scenario parsing -------------------------------------------------------
static void load_scenario(const char *path) {
    std::ifstream f(path);
    if (!f.is_open()) return;
    std::string line;
    while (std::getline(f, line)) {
        if (line.empty() || line[0] == '#') continue;
        std::istringstream ss(line);
        std::string op;
        ss >> op;
        if (op == "TICKS") {
            ss >> g_ticks;
        } else if (op == "TICK_US") {
            ss >> g_tick_us;
        } else if (op == "WATCH") {
            int p;
            while (ss >> p) g_watch.push_back(p);
        } else if (op == "EV") {
            Event e{};
            std::string kind;
            ss >> e.tick >> kind >> e.pin >> e.value;
            e.kind = (kind == "digital") ? 1 : 0;
            g_events.push_back(e);
        }
    }
}

static void apply_events(long tick) {
    for (const Event &e : g_events) {
        if (e.tick != tick) continue;
        vhw::PinState &p = vhw::machine().pin(e.pin);
        if (e.kind == 1) {
            p.digital = e.value ? HIGH : LOW;
        } else {
            p.analog_in = (int)e.value;
        }
    }
}

static std::string pin_snapshot_json() {
    std::string out = "{";
    bool first = true;
    for (const auto &kv : vhw::machine().pins) {
        if (!first) out += ",";
        first = false;
        char buf[256];
        snprintf(buf, sizeof(buf),
                 "\"%d\":{\"mode\":%d,\"digital\":%d,\"pwm\":%d,\"analog_in\":%d,"
                 "\"writes\":%ld,\"transitions\":%ld}",
                 kv.first, kv.second.mode, kv.second.digital, kv.second.pwm,
                 kv.second.analog_in, kv.second.writes, kv.second.transitions);
        out += buf;
    }
    out += "}";
    return out;
}

}  // namespace harness

int main(int argc, char **argv) {
    const char *scenario = (argc > 1) ? argv[1] : "scenario.txt";
    harness::install_guards(10);
    harness::load_scenario(scenario);

    vhw::Machine &m = vhw::machine();
    std::string timeline = "[";
    size_t uart_cursor = 0;

    // ---- setup() ----------------------------------------------------------
    harness::g_phase = "setup";
    harness::apply_events(-1);  // tick -1 events land before setup()
    setup();

    std::string setup_uart = m.uart.substr(uart_cursor);
    uart_cursor = m.uart.size();

    // ---- loop() ticks ------------------------------------------------------
    harness::g_phase = "loop";
    bool first_entry = true;
    for (long t = 0; t < harness::g_ticks; ++t) {
        harness::g_current_tick = t;
        harness::apply_events(t);

        unsigned long before_us = m.micros_clock;
        loop();
        m.loop_count++;

        // Guarantee forward progress of the virtual clock even for sketches
        // that never call delay(): one tick == one scheduling quantum.
        unsigned long consumed = m.micros_clock - before_us;
        if (consumed < harness::g_tick_us) {
            vhw::advance_us(harness::g_tick_us - consumed);
        }

        std::string delta = m.uart.substr(uart_cursor);
        uart_cursor = m.uart.size();

        char head[128];
        snprintf(head, sizeof(head), "%s{\"t\":%ld,\"ms\":%lu,\"pins\":",
                 first_entry ? "" : ",", t, m.micros_clock / 1000UL);
        first_entry = false;
        timeline += head;
        timeline += harness::pin_snapshot_json();
        timeline += ",\"uart\":\"" + harness::esc(delta) + "\"}";
    }
    timeline += "]";

    // ---- observation envelope ---------------------------------------------
    harness::g_phase = "report";
    printf("\n<<<FWAI_JSON>>>{");
    printf("\"status\":\"ok\",");
    printf("\"ticks_executed\":%ld,", harness::g_ticks);
    printf("\"tick_us\":%lu,", harness::g_tick_us);
    printf("\"elapsed_ms\":%lu,", m.micros_clock / 1000UL);
    printf("\"serial_begun\":%s,", m.serial_begun ? "true" : "false");
    printf("\"serial_baud\":%ld,", m.serial_baud);
    printf("\"setup_uart\":\"%s\",", harness::esc(setup_uart).c_str());
    printf("\"uart\":\"%s\",", harness::esc(m.uart).c_str());
    printf("\"pins\":%s,", harness::pin_snapshot_json().c_str());
    printf("\"timeline\":%s", timeline.c_str());
    printf("}\n");
    fflush(stdout);
    return 0;
}
