/*
 * arduino_shim.h — Virtual Arduino Hardware Abstraction Layer
 * ============================================================
 * A deterministic, host-compilable re-implementation of the Arduino core API.
 *
 * The firmware under test is compiled *unmodified* against this header, so the
 * real control-flow of the sketch executes natively.  Every peripheral
 * interaction is routed through a virtual machine model:
 *
 *   - Digital/analog pins are backed by an observable pin-state table.
 *   - Time (`millis`, `micros`, `delay`) is a virtual clock driven by the
 *     harness — execution is therefore 100% deterministic & reproducible.
 *   - `Serial` writes into an in-memory UART buffer captured by the harness.
 *   - Analog inputs are fed by scripted stimulus channels (virtual sensors).
 *
 * NOTE: this is a *simulation*, not an instruction-accurate emulation.  It
 * models the peripheral contract, which is what black-box firmware behaviour
 * testing needs.  For cycle-accurate execution swap in the Renode backend.
 */
#ifndef FIRMWAREAI_ARDUINO_SHIM_H
#define FIRMWAREAI_ARDUINO_SHIM_H

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <map>
#include <sstream>
#include <iostream>
#include <algorithm>

// ---------------------------------------------------------------------------
// Core constants
// ---------------------------------------------------------------------------
#define HIGH 1
#define LOW 0
#define INPUT 0
#define OUTPUT 1
#define INPUT_PULLUP 2
#define LSBFIRST 0
#define MSBFIRST 1
#define CHANGE 1
#define FALLING 2
#define RISING 3
#define DEC 10
#define HEX 16
#define OCT 8
#define BIN 2

#define A0 14
#define A1 15
#define A2 16
#define A3 17
#define A4 18
#define A5 19
#define A6 20
#define A7 21
#define LED_BUILTIN 13

#ifndef PI
#define PI 3.1415926535897932384626433832795
#endif

typedef uint8_t byte;
typedef bool boolean;

#define F(str) (str)
#define PROGMEM
#define PSTR(s) (s)

// ---------------------------------------------------------------------------
// Virtual machine state
// ---------------------------------------------------------------------------
namespace vhw {

struct PinState {
    int mode = -1;        // -1 unset, 0 INPUT, 1 OUTPUT, 2 INPUT_PULLUP
    int digital = 0;      // last digitalWrite value / driven input level
    int pwm = -1;         // last analogWrite duty (-1 = never written)
    int analog_in = 0;    // scripted ADC counts for analog reads
    long writes = 0;      // number of digitalWrite/analogWrite operations
    long transitions = 0; // number of value *changes* (chatter detection)
};

struct Machine {
    std::map<int, PinState> pins;
    unsigned long micros_clock = 0;   // virtual time base
    unsigned long delay_budget_us = 0;// accumulated delay (watchdog)
    std::string uart;                 // captured Serial output
    long serial_baud = 0;
    bool serial_begun = false;
    long loop_count = 0;

    PinState &pin(int p) { return pins[p]; }
};

inline Machine &machine() {
    static Machine m;
    return m;
}

inline void advance_us(unsigned long us) { machine().micros_clock += us; }

}  // namespace vhw

// ---------------------------------------------------------------------------
// Minimal Arduino String
// ---------------------------------------------------------------------------
class String {
   public:
    std::string s;
    String() {}
    String(const char *v) : s(v ? v : "") {}
    String(const std::string &v) : s(v) {}
    String(char v) : s(1, v) {}
    String(int v) { s = std::to_string(v); }
    String(long v) { s = std::to_string(v); }
    String(unsigned int v) { s = std::to_string(v); }
    String(unsigned long v) { s = std::to_string(v); }
    String(double v, int digits = 2) {
        char buf[64];
        snprintf(buf, sizeof(buf), "%.*f", digits, v);
        s = buf;
    }
    String(float v, int digits = 2) {
        char buf[64];
        snprintf(buf, sizeof(buf), "%.*f", digits, (double)v);
        s = buf;
    }

    const char *c_str() const { return s.c_str(); }
    unsigned length() const { return (unsigned)s.size(); }
    String operator+(const String &o) const { return String(s + o.s); }
    String operator+(const char *o) const { return String(s + std::string(o ? o : "")); }
    String &operator+=(const String &o) { s += o.s; return *this; }
    String &operator+=(const char *o) { if (o) s += o; return *this; }
    bool operator==(const String &o) const { return s == o.s; }
    bool operator==(const char *o) const { return o && s == std::string(o); }
    bool operator!=(const String &o) const { return s != o.s; }
    char charAt(unsigned i) const { return i < s.size() ? s[i] : '\0'; }
    int indexOf(const String &o) const {
        size_t p = s.find(o.s);
        return p == std::string::npos ? -1 : (int)p;
    }
    String substring(unsigned a) const { return a <= s.size() ? String(s.substr(a)) : String(""); }
    String substring(unsigned a, unsigned b) const {
        if (a > s.size()) return String("");
        return String(s.substr(a, b > a ? b - a : 0));
    }
    int toInt() const { return atoi(s.c_str()); }
    float toFloat() const { return (float)atof(s.c_str()); }
    void trim() {
        size_t b = s.find_first_not_of(" \t\r\n");
        size_t e = s.find_last_not_of(" \t\r\n");
        s = (b == std::string::npos) ? "" : s.substr(b, e - b + 1);
    }
};

inline String operator+(const char *a, const String &b) { return String(std::string(a ? a : "") + b.s); }

// ---------------------------------------------------------------------------
// Serial (virtual UART)
// ---------------------------------------------------------------------------
class SerialClass {
   public:
    void begin(long baud = 9600) {
        vhw::machine().serial_baud = baud;
        vhw::machine().serial_begun = true;
    }
    void end() { vhw::machine().serial_begun = false; }
    operator bool() const { return true; }
    int available() { return 0; }
    int read() { return -1; }
    void flush() {}

    void write(const char *v) { emit(v ? v : ""); }
    void write(char v) { emit(std::string(1, v)); }

    void print(const char *v) { emit(v ? v : ""); }
    void print(const std::string &v) { emit(v); }
    void print(const String &v) { emit(v.s); }
    void print(char v) { emit(std::string(1, v)); }
    void print(int v, int base = DEC) { emit(fmt_int((long)v, base)); }
    void print(long v, int base = DEC) { emit(fmt_int(v, base)); }
    void print(unsigned int v, int base = DEC) { emit(fmt_int((long)v, base)); }
    void print(unsigned long v, int base = DEC) { emit(fmt_int((long)v, base)); }
    void print(double v, int digits = 2) { emit(fmt_float(v, digits)); }
    void print(float v, int digits = 2) { emit(fmt_float((double)v, digits)); }
    void print(bool v) { emit(v ? "1" : "0"); }

    void println() { emit("\n"); }
    void println(const char *v) { emit(std::string(v ? v : "") + "\n"); }
    void println(const std::string &v) { emit(v + "\n"); }
    void println(const String &v) { emit(v.s + "\n"); }
    void println(char v) { emit(std::string(1, v) + "\n"); }
    void println(int v, int base = DEC) { emit(fmt_int((long)v, base) + "\n"); }
    void println(long v, int base = DEC) { emit(fmt_int(v, base) + "\n"); }
    void println(unsigned int v, int base = DEC) { emit(fmt_int((long)v, base) + "\n"); }
    void println(unsigned long v, int base = DEC) { emit(fmt_int((long)v, base) + "\n"); }
    void println(double v, int digits = 2) { emit(fmt_float(v, digits) + "\n"); }
    void println(float v, int digits = 2) { emit(fmt_float((double)v, digits) + "\n"); }
    void println(bool v) { emit(v ? "1\n" : "0\n"); }

   private:
    static std::string fmt_int(long v, int base) {
        char buf[72];
        if (base == HEX) snprintf(buf, sizeof(buf), "%lX", v);
        else if (base == OCT) snprintf(buf, sizeof(buf), "%lo", v);
        else if (base == BIN) {
            std::string b;
            unsigned long u = (unsigned long)v;
            if (u == 0) b = "0";
            while (u) { b = char('0' + (u & 1)) + b; u >>= 1; }
            return b;
        } else snprintf(buf, sizeof(buf), "%ld", v);
        return buf;
    }
    static std::string fmt_float(double v, int digits) {
        char buf[72];
        snprintf(buf, sizeof(buf), "%.*f", digits, v);
        return buf;
    }
    void emit(const std::string &chunk) {
        // Cap UART capture so a runaway sketch cannot exhaust host memory.
        std::string &u = vhw::machine().uart;
        if (u.size() < 512u * 1024u) u += chunk;
    }
};

static SerialClass Serial;
static SerialClass Serial1;

// ---------------------------------------------------------------------------
// GPIO
// ---------------------------------------------------------------------------
inline void pinMode(int pin, int mode) {
    vhw::PinState &p = vhw::machine().pin(pin);
    p.mode = mode;
    if (mode == INPUT_PULLUP) p.digital = HIGH;
}

inline void digitalWrite(int pin, int value) {
    vhw::PinState &p = vhw::machine().pin(pin);
    int v = value ? HIGH : LOW;
    if (p.writes > 0 && p.digital != v) p.transitions++;
    p.digital = v;
    p.pwm = v ? 255 : 0;
    p.writes++;
}

inline int digitalRead(int pin) { return vhw::machine().pin(pin).digital ? HIGH : LOW; }

inline int analogRead(int pin) {
    vhw::PinState &p = vhw::machine().pin(pin);
    vhw::advance_us(100);  // ADC conversion time on AVR ≈ 100 µs
    return p.analog_in;
}

inline void analogWrite(int pin, int value) {
    vhw::PinState &p = vhw::machine().pin(pin);
    int v = value < 0 ? 0 : (value > 255 ? 255 : value);
    if (p.writes > 0 && p.pwm != v) p.transitions++;
    p.pwm = v;
    p.digital = v > 0 ? HIGH : LOW;
    p.writes++;
}

inline void analogReference(int) {}
inline void analogReadResolution(int) {}

// ---------------------------------------------------------------------------
// Time (virtual clock)
// ---------------------------------------------------------------------------
inline unsigned long micros() { return vhw::machine().micros_clock; }
inline unsigned long millis() { return vhw::machine().micros_clock / 1000UL; }

inline void delayMicroseconds(unsigned int us) {
    // Watchdog: total simulated delay is bounded so blocking sketches cannot
    // stall the harness forever.
    vhw::Machine &m = vhw::machine();
    m.delay_budget_us += us;
    if (m.delay_budget_us > 600UL * 1000UL * 1000UL) {
        std::cerr << "[shim] delay budget exceeded — aborting\n";
        std::exit(42);
    }
    vhw::advance_us(us);
}

inline void delay(unsigned long ms) { delayMicroseconds((unsigned int)std::min<unsigned long>(ms * 1000UL, 4000000UL)); }

// ---------------------------------------------------------------------------
// Math / bit helpers
// ---------------------------------------------------------------------------
inline long map(long x, long in_min, long in_max, long out_min, long out_max) {
    if (in_max == in_min) return out_min;
    return (x - in_min) * (out_max - out_min) / (in_max - in_min) + out_min;
}
template <typename T, typename L, typename H>
inline T constrain(T x, L lo, H hi) { return x < (T)lo ? (T)lo : (x > (T)hi ? (T)hi : x); }

inline long random(long howbig) { return howbig <= 0 ? 0 : (rand() % howbig); }
inline long random(long howsmall, long howbig) {
    return howbig <= howsmall ? howsmall : howsmall + (rand() % (howbig - howsmall));
}
inline void randomSeed(unsigned long seed) { srand((unsigned)seed); }

#define bitRead(value, bit) (((value) >> (bit)) & 0x01)
#define bitSet(value, bit) ((value) |= (1UL << (bit)))
#define bitClear(value, bit) ((value) &= ~(1UL << (bit)))
#define bitWrite(value, bit, bitvalue) ((bitvalue) ? bitSet(value, bit) : bitClear(value, bit))
#define lowByte(w) ((uint8_t)((w) & 0xff))
#define highByte(w) ((uint8_t)((w) >> 8))

inline void attachInterrupt(int, void (*)(), int) {}
inline void detachInterrupt(int) {}
inline int digitalPinToInterrupt(int p) { return p; }
inline void noInterrupts() {}
inline void interrupts() {}
inline void wdt_reset() {}

// Forward declarations provided by the sketch under test.
void setup();
void loop();

#endif  // FIRMWAREAI_ARDUINO_SHIM_H
