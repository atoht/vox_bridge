class PcmWorkletProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    // Voxtral Realtime 使用 16kHz mono PCM16（pcm_s16le）。
    this.targetSampleRate = 16000;
    this.sourceSampleRate = sampleRate;
    this.ratio = this.sourceSampleRate / this.targetSampleRate;
    this.sourcePosition = 0;
    this.leftover = new Float32Array(0);
    this.pending = [];
    this.pendingLength = 0;
    this.frameSize = 1600; // 约 100ms，延迟和 WebSocket 开销之间的折中。
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0] || input[0].length === 0) {
      return true;
    }

    const channel = input[0];
    const combined = new Float32Array(this.leftover.length + channel.length);
    combined.set(this.leftover, 0);
    combined.set(channel, this.leftover.length);

    const output = [];
    while (this.sourcePosition + 1 < combined.length) {
      const index = Math.floor(this.sourcePosition);
      const weight = this.sourcePosition - index;
      output.push(combined[index] * (1 - weight) + combined[index + 1] * weight);
      this.sourcePosition += this.ratio;
    }

    const consumed = Math.floor(this.sourcePosition);
    this.leftover = combined.subarray(consumed);
    this.sourcePosition -= consumed;

    if (output.length === 0) {
      return true;
    }

    this.enqueuePcm(Float32Array.from(output));
    return true;
  }

  enqueuePcm(floatSamples) {
    const pcm = new Int16Array(floatSamples.length);
    for (let i = 0; i < floatSamples.length; i += 1) {
      const sample = Math.max(-1, Math.min(1, floatSamples[i]));
      pcm[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
    }

    this.pending.push(pcm);
    this.pendingLength += pcm.length;

    while (this.pendingLength >= this.frameSize) {
      const frame = new Int16Array(this.frameSize);
      let offset = 0;
      while (offset < this.frameSize && this.pending.length > 0) {
        const head = this.pending[0];
        const need = this.frameSize - offset;
        if (head.length <= need) {
          frame.set(head, offset);
          offset += head.length;
          this.pending.shift();
        } else {
          frame.set(head.subarray(0, need), offset);
          this.pending[0] = head.subarray(need);
          offset += need;
        }
      }
      this.pendingLength -= this.frameSize;
      this.port.postMessage(frame.buffer, [frame.buffer]);
    }
  }
}

registerProcessor("pcm-worklet-processor", PcmWorkletProcessor);
