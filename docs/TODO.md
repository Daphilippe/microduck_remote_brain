# Deferred production work

The current deployment target is a trusted private development network. The following work is
explicitly deferred and is required before exposing a robot or telemetry to an untrusted network.

## Network security

- authenticate and authorize every remote robot command;
- add TLS or a mutually authenticated tunnel for command and telemetry traffic;
- separate read-only monitor credentials from control credentials;
- add origin policy, rate limits and connection limits to the HTTP dashboard;
- define secret injection and rotation without committing credentials;
- audit firewall rules and bind defaults for public-network deployments.

## Physical safety

- implement a deterministic hardware safety provider using ToF/proximity, fall state, battery,
  command freshness and camera-frame freshness;
- require that provider before physical `allow_movement` can be enabled;
- feed head joints, trunk posture, and gravity through the Rust ToF reprojector for hardware stair
    and drop-off classification; the simulator already has a conservative lower-row memory latch;
- add an independently tested emergency-stop path and reconnect policy;
- negotiate robot capabilities and protocol versions at connection time.

## Media and monitoring

- implement the physical `mediad` H.264/WebRTC perception provider;
- move telemetry to a provider-neutral collector shared by simulator and hardware;
- add bounded history, metrics export and multi-client load tests;
- display data age and source identity on every monitoring view.

## Timeouts and remote links

No new short inference timeout is enabled for the current local GPU workflow. Before WAN or physical
deployment, define separate configurable policies for model inference, connection establishment,
robot command acknowledgement and sensor freshness. Validate those values under measured load rather
than copying development defaults.

## Operations

- publish versioned container images and a signed release process;
- add restart/upgrade/rollback tests and persistent audit retention policy;

## Deterministic navigation

- implement the pure relative-target control law described in `NAVIGATION.md`;
- add simulator arrival, obstacle, drop-memory, stall, timeout, and global-OFF integration tests;
- expose bounded relative targets to the persona and command center;
- add an optional laser-dot target provider only after bearing/confidence validation;
- calibrate walk and roller stopping/progress thresholds separately.
- add full MuJoCo integration tests to CI on a compatible Linux runner;
- document backup and privacy handling for images, audio, transcripts and personality memory.
