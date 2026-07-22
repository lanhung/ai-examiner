# v0.7 Real Audio Acceptance

Date: 2026-07-22

## Scope

This acceptance run used the local v0.7 release candidate at
`http://127.0.0.1:8016` with real provider credentials stored only in the ignored
local `.env` file. It exercised Qwen realtime WebSocket audio, OpenAI Realtime
WebRTC, browser microphone permission, PCM/RTP playback handling, event
persistence and microphone controls.

## Devices

- Input: Realtek microphone, 44.1 kHz Windows default endpoint.
- Output: Realtek speakers.
- A three-second direct microphone sample contained 120,414 non-zero samples,
  RMS 0.0033287 and peak 0.0594788.

## Results

### OpenAI Realtime WebRTC

- Model: `gpt-realtime-2.1`.
- Peer connection and realtime data channel established successfully.
- The examiner produced one grounded opening question.
- First response latency, measured from `response.create`: 638 ms.
- Persisted result: one assistant turn, zero errors and no empty user turn in the
  final clean run.
- Microphone mute and resume controls changed both track state and visible status.

### Qwen realtime audio

- Model tested through the product: `qwen3-omni-flash-realtime`.
- The upstream session, streaming transcript and 24 kHz PCM audio deltas completed
  successfully after microphone input was gated during the opening turn.
- A direct protocol probe also confirmed `qwen-audio-3.0-realtime-flash` support
  for text conversation items on the configured generic endpoint.
- Qwen uses a WebSocket PCM path in this release; it is not the WebRTC path.

## Defects found and corrected

1. The browser started streaming microphone audio before the opening Qwen response.
   Ambient input could race `response.create`, leaving the UI waiting indefinitely.
2. OpenAI sent the microphone RTP track during its opening response. Quiet noise
   could create an empty user turn and an unnecessary repeated question.
3. First-response timing started before microphone permission and connection setup,
   overstating model latency.
4. Empty ASR completion events were persisted as user turns.

The client now keeps microphone uplink disabled until the first `response.done`,
uses a 12-second Qwen opening timeout, measures latency from the initial request,
and discards empty user transcripts.

## Residual limits

- The automated acoustic loopback used Windows speech synthesis. Browser echo
  cancellation correctly removed that speaker output, so it could not substitute
  for a human speaking into the microphone.
- Human-spoken ASR word accuracy, perceived voice quality and conversational
  interruption comfort remain listener acceptance items.
- Opening the microphone from another recording process produced enough noise to
  trigger a clarification response. In noisy rooms, push-to-talk remains the
  recommended fallback and VAD robustness needs continued evaluation.

## Acceptance status

- OpenAI WebRTC transport and first-response target below 1.5 seconds: PASS.
- Qwen streaming transport and browser PCM playback path: PASS.
- Physical microphone endpoint and mute/resume controls: PASS.
- Human ASR accuracy and subjective audio quality: PENDING LISTENER CHECK.
