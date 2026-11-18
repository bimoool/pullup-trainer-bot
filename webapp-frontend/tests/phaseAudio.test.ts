import assert from "node:assert/strict";
import { test } from "node:test";
import { cancelScheduledPhaseEndSound, schedulePhaseEndSound } from "../src/phaseAudio.ts";
import { setSoundVolumePercent } from "../src/sound.ts";

test("phase cue honors mute and scales its existing tone without changing timing or cancellation", () => {
  const original = globalThis.AudioContext;
  const ramps: [number, number][] = [];
  const starts: number[] = [];
  const stops: (number | undefined)[] = [];
  let contexts = 0;
  let frequency = 0;
  let wave = "";
  class AudioContextProbe {
    state = "running";
    currentTime = 10;
    destination = {};
    constructor() { contexts += 1; }
    createOscillator() {
      const oscillator = {
        frequency: { value: 0 }, type: "", connect() {},
        start(at: number) { starts.push(at); frequency = oscillator.frequency.value; wave = oscillator.type; },
        stop(at?: number) { stops.push(at); },
      };
      return oscillator;
    }
    createGain() {
      return { gain: { setValueAtTime() {}, linearRampToValueAtTime(value: number, at: number) { ramps.push([value, at]); } }, connect() {} };
    }
  }
  globalThis.AudioContext = AudioContextProbe as unknown as typeof AudioContext;
  try {
    setSoundVolumePercent(0);
    schedulePhaseEndSound(30);
    assert.equal(contexts, 0, "mute creates no audio context or oscillator");
    for (const [volume, expected] of [[100, 0.3], [50, 0.15], [5, 0.015]]) {
      schedulePhaseEndSound(30, volume);
      assert.deepEqual(ramps.slice(-2), [[expected, 40.02], [0, 40.35]]);
      assert.equal(starts.at(-1), 40);
      assert.equal(stops.at(-1), 40.4);
      assert.equal(frequency, 880);
      assert.equal(wave, "sine");
    }
    const scheduled = starts.length;
    schedulePhaseEndSound(30, 0);
    assert.equal(stops.at(-1), undefined, "muting cancels the already queued cue");
    schedulePhaseEndSound(0, 100);
    assert.equal(starts.length, scheduled, "mute and expired deadlines never schedule a new cue");
    cancelScheduledPhaseEndSound();
  } finally {
    globalThis.AudioContext = original;
    setSoundVolumePercent(100);
  }
});
