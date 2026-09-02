# Persona models and contracts

This note defines the separation between perception, personality, and expression. Whisper and
speech recognition remain out of scope for this phase.

## Decision

```text
JPEG 640x480 ──> SceneInterpreter ──> SceneState
ToF 8x8 ───────> DepthObservation ──> deterministic safety memory
                                         │
                                         v
PersonaState ─────────────────────> PersonaModel ──> PersonaIntent
                                                        │
                                                        v
                                             ActuatorResolver + gates
                                                   │             │
                                                   v             v
                                             robotd intents   VoiceStyle
```

The three boundaries are versioned contracts:

1. `SceneInterpreter` transforms an image and sensor readings into facts, without applying a
  personality or selecting an action;
2. `PersonaModel` transforms those facts and a small internal state into an expressive intent;
3. `ActuatorResolver` translates the intent into allowed actuators. It is deterministic, and its
  outputs always pass through the gates and `robotd`.

The personality model does not receive the image. Instructions printed in the scene therefore
cannot directly alter its prompt or action catalog.

## Level 1: observed scene

The current MuJoCo camera produces 640x480 frames at 30 fps while the interactive viewer is
synchronized at 50 Hz. There is no benefit in requesting a
higher model input resolution. The target semantic rate is 1 to 2 Hz; fast obstacle checks remain
in the ToF pipeline and `robotd`.

The semantic scene contract is:

```json
{
  "schema_version": 1,
  "captured_at": 0.0,
  "entities": [
    {
      "kind": "person",
      "bearing": "left",
      "proximity": "near",
      "confidence": 0.82
    }
  ],
  "free_floor": "unknown",
  "visibility": "good",
  "hazards": [],
  "summary": "A person is visible on the left."
}
```

Enums always include `unknown`. A distance inferred from an image alone is never safety evidence.
The persona receives `SceneState` together with left, center, and right ToF clearance. Deterministic
code handles obstacle sectors and remembers possible lower-field drop-offs for three clear frames;
the LLM cannot override those restrictions.

### Local candidates

| Model | Approximate footprint | Use | Decision |
| --- | ---: | --- | --- |
| `qwen3.5:0.8b` | 1.0 GB in Ollama | 201-language VLM, image + text, short output | first local candidate; benchmark required |
| `Florence-2-base-ft` | 0.23B, about 0.5 GB FP16 | captioning, detection, grounding, segmentation | best specialized candidate |
| `qwen2.5vl:3b` | 3.2 GB in Ollama | robust grounding and visual JSON | quality oracle for tests |
| `SmolVLM2-500M` | 0.5B | low-footprint image and video | Transformers fallback candidate |

`qwen3.5:0.8b` offers the shortest Ollama integration path. It must still be compared with
`qwen2.5vl:3b` on real camera images: a small VLM is accepted only if it correctly detects people,
obstacles, and unknown space while respecting the schema.

Florence-2 is easier to port to ONNX than a conversational VLM, but its RKNN conversion and RK3566
performance are not established. It must not be treated as an embedded model before it is
benchmarked on the board.

### Embedded path

The credible MicroDuck path is already demonstrated by `duck-detect`: YOLO11n INT8 at 320x320,
3.9 MB, with measured latency of 25.7 ms p50 and 58.4 ms p95 on the RK3566 0.8 TOPS NPU. This model
does not produce a general description; it publishes compact detections.

The migration should therefore preserve the same `SceneState` with two providers:

- local PC: VLM over the 640x480 JPEG, resized by its processor;
- robot: 320x320 RKNN detectors + ToF + IMU, followed by a symbolic summary without an embedded
  VLM.

Several specialized micro-detectors can replace one large model: person, MicroDuck, ball, and
traversable obstacle. They all publish `EntityObservation` values; none commands the robot.

## Level 2: personality

The persona does not need broad knowledge or long reasoning. It must quickly produce 40 to 120
structured tokens and maintain a consistent configured voice.

```json
{
  "schema_version": 1,
  "behavior": "greet_person",
  "utterance": "Oh, hello there.",
  "affect": "curious",
  "energy": 0.45,
  "gesture": "look_at_subject"
}
```

| Model | Approximate Q4 GGUF | Positioning |
| --- | ---: | --- |
| `Qwen3-0.6B` | 429 MB | throughput ceiling, useful for measuring minimum quality |
| `Qwen3.5-0.8B` | about 1 GB with vision encoder | first Ollama candidate, but vision weights are wasted here |
| `Qwen3-1.7B` | 1.28 GB | compact quality reference under Apache-2.0 |
| `Llama-3.2-1B-Instruct` | about 0.8 GB | good French, more restrictive community license |

The measured default is `qwen3:0.6b` through Ollama. On the local RTX 3060, the production persona
contract reached 135.7 decode tokens/s with 341.6 ms p50 and 395.6 ms p95. `qwen3:1.7b` reached
114.2 tokens/s with 356.7 ms p50 and 466.8 ms p95. These measurements cover eight decisions after
warmup and are a local selection result, not a general model benchmark.

Recommended serving parameters: 4096-token context, GPU-appropriate batch size, thinking disabled,
96-token maximum output, and a JSON schema. A 32K or 256K context wastes KV memory here without
improving behavior.

## Level 3: actuators and modulation

`PersonaIntent` contains intents, never joint velocities. A resolver maps each intent to one or
more available actuators.

The implemented autonomous subset uses `walk_forward`, `curve_left`, `curve_right`, `back_up`,
`turn_left`, `turn_right`, `ground_pick`, `tap_left`, and `tap_right`, plus the closed sound
vocabulary and `stop`. A three-entry activity window requires two physical behaviors whenever at
least one passes the deterministic scene, depth, and drop-memory gates. This policy uses relative
observations and therefore does not encode a particular simulation environment.

The runtime additionally filters `roulade`, `sit_toggle`, ball kicks, and `ground_pick` against the
skill filenames returned by `robot.subscribe` and the current `robot.mode`. `scan_left`,
`scan_right`, and `scan_center` produce body-stopped `robot.look` plans. `sing` produces a bounded
sound phrase; it is distinct from the opt-in multi-duck `robot.chorale` protocol.

| Family | Intents exposed to the persona | Implementation |
| --- | --- | --- |
| gaze | `look_at_subject`, `look_left`, `look_right`, `scan` | `robot.look` or `robot.head` |
| posture | `neutral`, `crouch`, `lean`, `ruffle` | `robot.pose`, within trained bounds |
| locomotion | `approach`, `retreat`, `turn`, `stop` | ONNX walking policy + deadman |
| skills | `sit_toggle`, `ground_pick`, `kick`, `roulade` | `robot.do`, strict preconditions |
| face | `mouth_open`, simple lip synchronization | `robot.mouth`, value bounded to 0..1 |
| duck voice | `alarm`, `greet`, `inquire`, `peck`, `chirp`, `coo` | `robot.sound` bank |
| instrument | `theremin_on`, `theremin_off` | `robot.theremin` |

The locomotion and skill ONNX policies already are the actuator micro-models: they receive 61
values and produce 14 actions at 50 Hz. The LLM selects a high-level intent; it selects neither the
policy file nor the 14 outputs.

For future synthesized speech, the contract must remain closed: text, voice, and one style from
`calm`, `curious`, `happy`, and `concerned`. Kokoro-82M is the first lightweight candidate for
French and speed control. CosyVoice2-0.5B is the candidate when native control of emotion, rate,
and volume becomes a priority. This output does not depend on Whisper.

## Provider decision

Ollama is the default and currently the only remote-brain model provider. It already owns model
discovery, preflight, vision requests, and persona requests in this project. The two contracts use
separate Ollama model names but share the configured endpoint.

The llama.cpp installation at `F:/IA/LLM/llama.cpp` is not part of the current runtime. It remains
a possible future provider only if a text model is deployed directly on MicroDuck. Such a port
must preserve `PersonaIntent`; it must not introduce a second planning contract or motor path.

## Selection protocol

Build a versioned corpus of 100 to 300 cycles containing a 640x480 JPEG, ToF/IMU readings, expected
`SceneState`, persona state, and the set of acceptable intents.

Measure each layer separately:

- perception: person and obstacle recall, false positives, `unknown` field rate, schema compliance,
  p50/p95 latency, and images/s;
- persona: valid JSON, allowed intent, consistency with hazards, diversity, French quality,
  time-to-first-token, tokens/s, and total latency;
- resolution: refusal when a capability or required evidence is missing, independently of the
  model.

Initial persona threshold: 100% parseable JSON under the grammar, 100% of actions in the catalog,
no accepted movement on dangerous corpus scenes, and p95 below 500 ms on the local PC. Expressive
quality then distinguishes models that pass these constraints.

Evaluation order:

1. use a larger VLM only as a temporary oracle for corpus annotation;
2. validate `qwen3.5:0.8b` against Florence-2-base-ft and `qwen2.5vl:3b` for `SceneState`;
3. rerun `scripts/benchmark_persona.py` whenever the prompt, schema, model, or GPU changes;
4. extend the Python executor with the `look`, `pose`, `mouth`, and `do` intents;
5. keep provider changes behind the same scene and persona contracts.