export type RecorderHandle = {
  stop: () => Promise<void>;
};

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  // 分块转换，避免长音频 chunk 导致调用栈过深。
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    const chunk = bytes.subarray(i, i + chunkSize);
    binary += String.fromCharCode(...chunk);
  }
  return btoa(binary);
}

export async function startPcmRecorder(
  onAudioChunk: (base64Pcm16: string) => void,
): Promise<RecorderHandle> {
  // 浏览器必须在 HTTPS 或 localhost 下才允许读取麦克风。
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    },
  });

  const audioContext = new AudioContext();
  await audioContext.audioWorklet.addModule("/audio-processor.js");

  const source = audioContext.createMediaStreamSource(stream);
  const worklet = new AudioWorkletNode(audioContext, "pcm-worklet-processor");

  worklet.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
    onAudioChunk(arrayBufferToBase64(event.data));
  };

  source.connect(worklet);
  // 连接到静音增益节点，确保部分浏览器持续拉取 AudioWorklet。
  const silentGain = audioContext.createGain();
  silentGain.gain.value = 0;
  worklet.connect(silentGain);
  silentGain.connect(audioContext.destination);

  return {
    stop: async () => {
      worklet.port.onmessage = null;
      worklet.disconnect();
      source.disconnect();
      silentGain.disconnect();
      stream.getTracks().forEach((track) => track.stop());
      await audioContext.close();
    },
  };
}
