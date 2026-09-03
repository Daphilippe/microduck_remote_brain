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

`RobotOdometryProvider` subscribes to `robot.state` and reads odometry X/Y/yaw plus the robot
timestamp. When gravity, gyroscope, or quaternion evidence is present, it rejects implausible pose
jumps and blends valid odometry deltas with commanded velocity and gyro yaw. This supplies the
stable pose contract used by mapping without reading simulator-truth trunk coordinates. Existing
ToF sector summaries and `DropHazardMemory` provide local obstacle and floor-continuity evidence.

The occupancy mapping work exposes `Pose2D`, `PlanarScan`, `OccupancyGridMapper`, and
`MappingSession`. Autonomy consumes that API without redefining it. Scripted skills capture a pose
anchor through the same mapping oracle before execution. A future return controller should accept
that anchor as a target and use the occupancy grid for collision-aware restoration.

Until path planning consumes the grid, acquisition uses a local deterministic fallback: a complete
failed head scan rotates the trunk toward the clearer ToF side with zero linear velocity. This
changes viewpoint without pretending to solve global navigation.

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

Until those tests pass, autonomous roulade remains disabled because it can invalidate the current
pose. This is preferable to claiming position continuity that the present time-based action plans do
not provide.

## Persistent mapping

Persistent mapping belongs in `microduck_remote_brain` because reconstruction, map storage, change
detection, and global planning run on the remote computer. Hardware daemons remain responsible for
calibrated, timestamped sensor samples and motor safety. The mapper consumes contracts rather than
MuJoCo objects or physical device APIs, so simulation and hardware feed the same pipeline.

The first implemented layer is deliberately geometric and deterministic:

```text
camera frame + ToF frame + body pose
                 |
                 v
          MappingSession
        /                \
occupancy evidence    RGB/depth/pose keyframes
        |                       |
persistent 2D grid       future splat backend
        |
global costmap and planner
```

`OccupancyGridMapper` ray-casts `PlanarScan` observations into a versioned evidence grid. Repeated
free observations reduce occupancy evidence and repeated returns increase it. A cell is reported as
changed only when its classified state crosses unknown, free, or occupied. The map and
`localization.json` are replaced atomically after each accepted observation, allowing pose and grid
state to survive process restarts.

`MappingSession` also archives each JPEG with pose and range metadata. Those keyframes are the input
boundary for an offline or incremental Gaussian Splat backend. Splats must remain a visual and
semantic memory used for relocalization, inspection, and change proposals; they are not the sole
collision map. Any change inferred from imagery must be confirmed by geometric observations before
it changes traversability.

The simulator profile enables this pipeline and writes under `.local/maps`. The physical example
keeps it disabled. Enabling physical mapping requires one provider to deliver:

1. monotonic sensor timestamps from a shared or calibrated clock;
2. odometry poses in a stable `map` or `odom` frame, including covariance;
3. calibrated LiDAR/ToF beam directions and the sensor-to-trunk transform at capture time;
4. camera intrinsics, distortion parameters, exposure timestamp, and camera-to-trunk transform;
5. validity/status values for every range return;
6. loop-closure corrections without silently mixing incompatible map frames.

The current simulated VL53L5CX observation is collapsed from 8x8 zones to eight horizontal rays by
taking the nearest valid range in each column. This is sufficient to exercise persistence and map
change mechanics, but it is not a physical 2.5D traversability model. Floor/obstacle classification,
head-pose reprojection, elevation, slope, and foothold costs must be added before map-based movement
is enabled on the robot.

Recommended next delivery stages:

1. expose synchronized pose, camera, and calibrated ToF frames through the physical gateway;
2. add a 2.5D elevation/traversability layer and local dynamic obstacle layer;
3. consume the occupancy/traversability map in a deterministic global planner;
4. add loop closure and map-frame correction;
5. train or integrate the Gaussian Splat backend from archived keyframes;
6. promote persistent visual changes only after multi-view geometric confirmation.

## Implemented exploration and startup localization

The active mapping path does not consume the simulator `trunk` position. `RobotOdometryProvider`
subscribes to `robot.state` and uses `odom.position`, `odom.yaw`, and the robot timestamp. This is
the same odometry contract expected from physical `robotd`. Maps and localization records declare
`pose_source = "robotd_odometry"`; maps created by the earlier simulator-truth prototype are moved
to `occupancy-map.legacy-simulator-truth.json` instead of being merged.

At startup, a new map accepts robot odometry as its initial coordinate frame. For an existing map,
the last persistent pose is only a search seed. The current ToF scan is correlated against occupied
cells in a bounded translation and yaw window. If matching fails, the autonomous loop performs up
to six one-second in-place turns, checking ToF side clearance before every turn. It does not append
unlocalized observations to the persistent map. A successful match establishes the `map <- odom`
anchor used for subsequent poses.

After localization, the remote brain keeps `ExplorationPolicy` active instead of treating an
arbitrary global coverage percentage as completion. It alternates shallow curves through clear
space and periodic turns to expose new frontiers. A blocked center ray, remembered drop, or
asymmetric clearance overrides exploration toward the safer side. The remote brain selects and
sends the action, which still passes through `ActuatorResolver`, ToF gates, `PlanExecutor`, robot
deadman handling, and the global action-disable latch.

The command center serves the persistent grid at `/api/map` and renders unknown, free, and occupied
cells at one update per second. Its duck marker comes from the persisted robot-odometry localization
record, never from `/api/state.trunk`. The panel shows map revision, coverage, pose source, and the
estimated position so accidental simulator-truth use remains visible during development.
