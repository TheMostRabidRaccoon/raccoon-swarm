# The raccoon body 🦝

The protocol explicitly does not care about the shell: *"The body is up to you."*
So the raccoon remix is fully sanctioned — but the mechanics below are load-bearing.
Break them and the walk policy stops matching reality.

## What must stay true (from the protocol appendix + build guide)

1. **Geometry the policy was trained for.** Flat base plate ≈ phone-sized
   (114 × 69 mm), phone + battery + Pico stacked in the middle, one servo at each
   end with output shafts pointing **outward**, a flat paddle leg on each horn
   (≈ 21 × 13 × 84 mm) sweeping the full 180°. The legs are arms on the servo
   outputs — nothing hangs below.
2. **The mirror rule.** Because the servos face outward, the same angle swings the
   legs opposite ways; matching motion means `l + r = 180`. Any remixed body must
   preserve this (or invert one side in firmware). Self-check: send `{l:50, r:130}`
   — the body should rise, not fold forward.
3. **Forward is where the screen faces.** Left/right are the creature's own, so its
   left leg is on your right when you face it. Put the raccoon's face on the
   screen side.
4. **Mass and balance.** The shipped walk policy balances the stock mass layout
   using the phone's IMU. Every gram of raccoon changes the dynamics — the policy
   tolerates some (it was trained with domain randomization), but a heavy or
   high-mounted addition will tip it.

## Remix guidelines

- **Keep additions light and low.** Ears, mask, and tail in PLA at low infill
  (10–15%), ideally hollow. Decoration should be grams, not tens of grams.
- **Keep the leg sweep clear.** Each servo sweeps its paddle through a full 180° arc
  at the ends of the body. Ears go on top of the phone end; nothing may enter the
  leg arcs. Dry-run the sweep by hand before powering servos.
- **Tail: start printed-in-place, angled up.** A raccoon needs a tail, but a hanging
  tail is a third contact point that drags and a pendulum the policy never saw.
  Angle it up and keep it short and light. (A servo-articulated tail is a lovely
  later upgrade — the N-servo direction in upstream VERBS.md §3 even sketches how
  extra channels get verbs — but V1 walks first.)
- **The mask is the identity.** Two-tone the face: dark mask band across the
  camera/eyes region of the phone mount, light muzzle below. Either two-color print,
  paint, or vinyl. Leave the camera and screen unobstructed — the robot sees and
  shows its face through them.
- **Symmetry left–right.** The policy assumes a symmetric body. Asymmetric flair
  (a jaunty ear tilt) is fine only if it's light enough not to matter.

## Practical path

1. Print the stock set first (upstream `hardware/print/`):
   `growbot_diy_body_v1.1_r01_beta_01.stl`, `growbot_diy_backplate_v1_r01.stl`,
   2× `growbot_diy_leg_v1_r01.stl`. Get it walking **stock** so there's a known-good
   baseline.
2. Remix pass: import the body STL into your CAD tool of choice and add ears/mask/tail
   as separate glue-on or clip-on pieces rather than editing the structural shell —
   additions can iterate without reprinting the body.
3. After each addition, re-run the wiggle test and a short walk. If it face-plants,
   remove the newest piece — that's your culprit (almost always mass too high or
   too far forward).
4. Trophy shot for the build log when it walks in fur.
