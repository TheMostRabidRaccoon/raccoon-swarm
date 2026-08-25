# Shopping list — GrowBot V1 body

Straight from upstream [BOM.md](https://github.com/britcruise9/GrowBot/blob/main/BOM.md),
with the traps annotated. **~$30–43 total**, no soldering.

## Order these

| # | Part | Spec | Qty | ~USD | Notes / traps |
|---|------|------|----:|-----:|---------------|
| 1 | Raspberry Pi Pico 2 W | RP2350, **W = Wi-Fi** | 1 | $7 | Adafruit, official resellers, AliExpress. The Wi-Fi is how the brain talks to the body — a non-W Pico is useless here. ESP32 is an acceptable substitute (different flashing path). |
| 2 | MG90S micro servo | metal gear, 9 g, **standard 180°** | 2 | $8/pair | ⚠️ THE trap: **NOT 360°/continuous-rotation** — they sell under nearly identical listings. A continuous servo reads an angle as a speed and can never hold a pose (symptom: legs spin on power-up, never stop). SG90s work but have weak plastic gears — a raccoon deserves metal. |
| 3 | Mini breadboard + dupont jumpers | | 1 set | $5 | Direct-wire path, the default. A Pico carrier board (~$13, screw terminals) is the tidier alternative. |
| 4 | AA lithium batteries | 1.5 V **single-use** (Energizer Ultimate type) | 4 | $15 | ⚠️ Exactly these. Not USB-rechargeable 1.5 V AAs (cut out under load), and **never 3.7 V 14500 cells** (destroy the board). Plain alkalines are OK to start — just heavier and weaker. Servos spike >2 A; weak supply = legs twitch, Pico brownout-resets. |
| 5 | 4×AA holder **with switch** | | 1 | $3 | The switch is the power button. |
| 6 | Two-sided foam tape | | 1 roll | $5 | The entire fastening system for phone + battery. |

## Already have / check

- **A phone** from the last ~6–7 years (the stock brain path; also handy for testing
  even though our long-run brain lives server-side). Compatibility check: growbot.dev/build.
- **3D printer access + PLA** for the body. Stock STLs are in upstream
  `hardware/print/` (plain PLA, no supports, legs screw onto servo horns, no glue).
  No printer → paper cutout template at upstream `hardware/cutout-template.html`,
  printed at 100%, built from any stiff material.
- **Raccoon remix extras** — see [RACCOON_BODY.md](RACCOON_BODY.md): filament for
  ears/mask/tail, optional 10 mm magnets (the stock phone plate has 10 mm magnet
  mounts), paint or a second filament color for the mask.

## Wiring (the whole thing)

Servo signals → GP0 (left) and GP1 (right). Both servo reds → battery +. One common
ground rail: battery −, a Pico GND pin, and both servo browns. Done.

USB power is fine for gentle desk tests; real walking needs the battery pack.
