# Shopping list — GrowBot V1 phone-brain body

**Build target:** GrowBot V1 with a phone brain, Raspberry Pi Pico 2 W body controller,
Waveshare Pico Servo Driver, and two MG90S servo legs.

**Our phones:** start with the unused **iPhone 15** as the first robot brain; the unused
**iPhone 17** is available for a second bot or fallback. A SIM is not required — Wi-Fi is
enough. Before ordering around a specific phone, open <https://growbot.dev/build> on that
phone and confirm the Step 00 compatibility check shows green.

## Source-of-truth note

Use the **live official build guide at <https://growbot.dev/build> for this build.**

Upstream `BOM.md` / `BUILD.md` on GitHub currently still describe a direct-wire
breadboard path (GP0/GP1, holder with switch). The live build guide has moved to the
carrier-board / no-solder path below. This file intentionally follows the **live guide**,
not the stale direct-wire BOM.

Official headline: about **30 minutes, ~$35 in parts, no soldering** when sourced cheaply
and assuming some household items are already on hand. US Amazon pricing will usually be
higher.

---

## US shopping list

Search these terms on **amazon.com** (the official guide currently links several Canadian
Amazon listings). Exact seller and price can vary.

| # | Search / part | Qty | Official ~USD | Notes / traps |
|---|---|---:|---:|---|
| 1 | `Raspberry Pi Pico 2 W with headers` | 1 | $7 | **Must be Pico 2 W and must already have header pins soldered on** for the no-solder build. A bare Pico requires soldering. The `W` provides Wi-Fi. |
| 2 | `Waveshare Pico Servo Driver` | 1 | $10–25 | Current live-guide carrier board and the board shown in the photos. Buy from Waveshare direct if materially cheaper. |
| 3 | `Miuzei MG90S metal gear servo 2 pack 180 degree` | 1 pair (2 servos) | ~$17/pair | **MG90S, metal gear, standard positional servo — not SG90 and not 360° / continuous rotation.** The live guide specifically says the Miuzei pair is field-confirmed to fit the printed body slots. |
| 4 | `AA lithium batteries` | 4 | varies | Current live guide says lithium **single-use or rechargeable** both work. The power system must stay above the board floor and deliver servo current spikes reliably. |
| 5 | `4 AA battery holder bare wire leads low profile` | 1 | varies | **No cover and no switch.** The live guide warns covered/switched holders are too large for the body slot. |
| 6 | `double sided foam mounting tape` | 1 roll | varies | Definitely used to mount the phone. The live parts list also mentions battery mounting, although the assembly section says the battery nests in the molded body slot; keep the tape either way. |
| 7 | `precision screwdriver set small phillips flat head` | 1 set | varies | Small Phillips for the leg screws; tiny flat-head for the battery screw terminal. A small pair of scissors can substitute for the flat-head in a pinch. |

### Do **not** substitute these casually

- **No bare-header Pico** unless we decide to solder.
- **No SG90** for the final walking build; the live guide says the plastic gears strip.
- **No 360° / continuous-rotation MG90S.** Standard 180° positional servos only.
- **No covered or switched AA holder** for the stock printed body.
- **No 5 GHz-only Wi-Fi network** for the Pico; its radio uses 2.4 GHz.

---

## Body

Stock body + legs are free from the official GrowBot build page / upstream hardware files
and are intended for plain PLA.

Options:

- **Print the STL body** ourselves / through local printer access.
- **Print-on-demand:** the live guide links a shipped body at about **$15**.
- **Same-day ugly-but-functional mode:** use the cut-from-anything template.

For the raccoon remix, see [RACCOON_BODY.md](RACCOON_BODY.md) for ears, mask, tail, and
other highly unnecessary but obviously mandatory trash-panda improvements.

---

## Already have / check before build day

- **iPhone 15** — intended first brain; Wi-Fi only is fine, no SIM required.
- **iPhone 17** — second brain / fallback / future second bot.
- **Mac** for the one computer-required setup step.
- **Desktop Chrome or Edge** on the Mac for the one-click Web Serial installer.
  Safari, Firefox, iPhone, and iPad cannot do that Web Serial step.
- **A data-capable USB cable for the Pico** (not power-only). The Pico 2 W uses its own
  micro-USB port during flashing.
- **2.4 GHz-capable Wi-Fi.** Most dual-band routers expose 2.4 + 5 GHz under one SSID and
  the Pico quietly uses 2.4. If the bands have separate names, give GrowBot the 2.4 GHz
  SSID. A phone hotspot can be a workaround if it supplies 2.4 GHz.

---

## Power requirements

For the **Waveshare Pico Servo Driver** path:

- supply floor: **at least 4.5 V**
- current: **steady ≥ 2 A** available; servos spike under movement/load
- twitching + board restarts usually means weak power

The live guide also allows other small 5 V supplies (for example a suitable USB power
bank, or a 1S LiPo plus boost board), but the 4×AA path is the stock build and what this
shopping list assumes.

**Never wire battery or servo power to the Pico's own pins.** The carrier board handles
power.

---

## Wiring for the current Waveshare build

Battery pack → carrier-board screw terminal:

- red → **+ / VIN**
- black → **− / GND**

Servos → carrier board:

- robot **left servo → socket `0`**
- robot **right servo → socket `1`**
- every other servo socket stays empty

Servo plug orientation follows the carrier-board labels:

- lightest wire (orange / yellow / white) = signal
- red = power
- darkest wire (brown / black) = ground

After the first power-up, the boot check centers both servos, moves right, moves left,
moves both, then holds at 90°. Attach the legs during/after that known 90° position so
they sit perpendicular to the body. Power-cycle afterward; **right leg should move solo
before left**. If not, swap the two servo plugs.

---

## First-build flow

1. Run the phone compatibility check on the **iPhone 15** at <https://growbot.dev/build>.
2. Order the parts above and print/order the body.
3. Seat the Pico on the Waveshare carrier board.
4. On the Mac, flash MicroPython via BOOTSEL, then use **desktop Chrome/Edge** for the
   official one-click installer.
5. Save the robot pairing code (`gb-……`) — it is that robot's persistent name.
6. On the iPhone 15, open <https://growbot.dev/tester>, Wake robot, enter the pairing code,
   and stop once the green online dot appears. Do not wiggle yet if servos are not installed.
7. Install board, servos, battery; wire power; connect servos to sockets `0` and `1`.
8. Run the boot movement check, attach legs at 90°, verify right-before-left.
9. Foam-tape the phone to the front, centered, camera at top.
10. Work through controller tabs: **Calibrate → Move → LLM → Agent**.

---

## Body-truth note for our harness

Upstream `agent-harness/body_truth.phone.json` is intentionally the **bare-phone** body:
`id: "phone-bare"`, no motors, with `say`, `sound`, `sing`, and `burst` verbs. That file is
correct for a phone with no limbs.

Once our physical raccoon has legs, our RRI harness must use a body-truth / verb contract
that includes the actual movement capabilities rather than accidentally pinning the
bare-phone contract. Our local movement contract currently lives at
`growbot/harness/body_truth_raccoon.json`; keep hardware capabilities and safety clamps
synchronized there as the body evolves.

---

## Cost sanity check

The official live guide still advertises roughly **$35 in parts** using inexpensive
sources. A one-off US Amazon build will likely cost more because the Waveshare board,
servos, batteries, tools, tape, and optional printed body are bought at retail rather
than assumed-on-hand. That is normal; prioritize exact compatibility over chasing the
headline price.
