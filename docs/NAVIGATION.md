# Deterministic local navigation

## Why theremin is not navigation

The existing `robot.theremin` mode is a ToF-driven musical interaction. It tracks the nearest hand
inside a playable distance band and maps that scalar range to pitch and mouth opening. It does not
produce velocity commands, estimate bearing, avoid obstacles, remember a route, or drive toward a
laser point. It must not be presented as a point-following controller.

A visible laser pointer could become a target source later, but it would require a camera detector
that publishes a bearing and confidence. The navigation controller described here is independent of
that source: a pointer, a UI click, or a high-level LLM intent may all supply the same bounded target.

## Responsibility split

```text
LLM / UI / pointer detector
        |
        v
bounded relative target (distance, bearing)
        |
        v
DeterministicTargetController
  - body XY + yaw feedback
  - ToF left/center/right clearance
  - persistent drop memory
  - timeout and progress watchdog
        |
        v
robot.move velocity setpoints -> robotd policy and deadman
```

The LLM chooses goals such as explore ahead, approach a visible object, or inspect a direction. It
does not choose every velocity sample. The local controller owns heading correction, progress,
obstacle response, target tolerance, and stopping.

## Available foundation

`BodySnapshot` preserves trunk X/Y, simulator time, and yaw reconstructed from the IMU quaternion.
This is enough to express a relative target in the world frame and measure progress. Existing ToF
sector summaries and `DropHazardMemory` provide local obstacle and floor-continuity evidence.

## Required controller contract

A target request must contain bounded relative distance and bearing, not an unrestricted world
coordinate from model text. Before each velocity update, the controller must:

1. read fresh body X/Y/yaw;
2. read a fresh ToF frame and update drop memory;
3. stop immediately when a drop is remembered;
4. turn in place when heading error is large;
5. advance only when center clearance permits it;
6. stop when target tolerance is reached, progress stalls, input becomes stale, or timeout expires.

The global `actions-disabled` latch and `robotd` deadman remain higher-priority boundaries.

## Roller mode

The target controller must query `robot.mode` before starting and during a long target. It may use the
same bounded velocity interface in walk and roller modes because robotd selects the corresponding
policy. Acceleration, stopping distance, and progress thresholds must be calibrated separately for
each mode. Autonomy must never switch to roller mode unless an external hardware capability confirms
that rollers are installed.

## Delivery stages

1. Add a pure target-control law with synthetic pose/depth tests.
2. Add a simulator-only relative-target executor with progress and timeout evidence.
3. Expose bounded targets through the command center and autonomous intent resolver.
4. Add a camera laser-dot detector as an optional target provider.
5. Implement hardware posture-aware ToF reprojection before enabling physical navigation.

Point-to-point navigation is not marked complete until an integration test demonstrates target
arrival, obstacle interruption, remembered-drop interruption, stalled-progress failure, and global
OFF cancellation.
