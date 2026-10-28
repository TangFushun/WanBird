/* 本机/USB 摄像头拍照。只申请视频权限；图像在内存中转为 JPG，沿用图片识别流程。 */
(function () {
  'use strict';
  const MAX_BYTES = 2 * 1024 * 1024;

  function cameraError(error) {
    switch (error && error.name) {
      case 'NotAllowedError':
      case 'SecurityError': return '摄像头权限未开启。请在浏览器的网站权限中允许摄像头，再点击“打开摄像头”。';
      case 'NotFoundError': return '没有找到可用摄像头。请连接本机或 USB 摄像头，确认系统已识别后重试。';
      case 'NotReadableError':
      case 'AbortError': return '摄像头暂时无法使用，可能被其他程序占用。请关闭占用摄像头的程序后重试。';
      case 'OverconstrainedError': return '所选摄像头已不可用或不支持当前设置。请刷新设备后重新选择。';
      default: return '无法打开摄像头，请检查设备连接和浏览器权限后重试。';
    }
  }

  async function photograph(video) {
    if (video.readyState < 2 || !video.videoWidth || !video.videoHeight) {
      throw new Error('画面尚未就绪，请稍候再拍照。');
    }
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('当前浏览器无法生成照片，请尝试其他浏览器。');
    // 完整保留画面比例；分辨率和 JPEG 质量逐级调整，满足现有接口的 2MB 限制。
    // 先冻结原始帧，后续压缩始终使用同一帧，避免编码期间画面变化。
    const scale = Math.min(1, 1600 / Math.max(video.videoWidth, video.videoHeight));
    canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
    canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    const output = document.createElement('canvas');
    const outputCtx = output.getContext('2d');
    if (!outputCtx) throw new Error('当前浏览器无法生成照片，请尝试其他浏览器。');
    for (const ratio of [1, .75, .5]) {
      output.width = Math.max(1, Math.round(canvas.width * ratio));
      output.height = Math.max(1, Math.round(canvas.height * ratio));
      outputCtx.drawImage(canvas, 0, 0, output.width, output.height);
      for (const quality of [.9, .75, .6]) {
        const blob = await new Promise(resolve => output.toBlob(resolve, 'image/jpeg', quality));
        if (!blob || !blob.size) throw new Error('照片生成失败，请重新拍照。');
        if (blob.size <= MAX_BYTES) {
          return new File([blob], 'camera-' + Date.now() + '.jpg', {type: 'image/jpeg'});
        }
      }
    }
    throw new Error('照片压缩后仍超过 2MB，请尝试降低摄像头分辨率。');
  }

  class BirdCamera {
    constructor(root, callbacks) {
      this.root = root;
      this.callbacks = callbacks;
      this.video = root.querySelector('#cameraVideo');
      this.devices = root.querySelector('#cameraDevice');
      this.status = root.querySelector('#cameraStatus');
      this.placeholder = root.querySelector('#cameraPlaceholder');
      this.startButton = root.querySelector('#cameraStart');
      this.captureButton = root.querySelector('#cameraCapture');
      this.previewButton = root.querySelector('#cameraPreview');
      this.refreshButton = root.querySelector('#cameraRefresh');
      this.stream = null;
      this.version = 0;
      this.listVersion = 0;
      this.active = false;
      this.pending = false;
      this.capturing = false;
      this.startButton.addEventListener('click', () => this.start(this.devices.value));
      root.querySelector('#cameraClose').addEventListener('click', () => this.close());
      this.devices.addEventListener('change', () => this.start(this.devices.value));
      this.refreshButton.addEventListener('click', () => this.refreshDevices());
      this.captureButton.addEventListener('click', () => this.capture(true));
      this.previewButton.addEventListener('click', () => this.capture(false));
      this.video.addEventListener('loadeddata', () => this.updateReady());
      this.video.addEventListener('canplay', () => this.updateReady());
      navigator.mediaDevices?.addEventListener?.('devicechange', () => {
        if (this.active) this.refreshDevices();
      });
      window.addEventListener('pagehide', () => this.close());
      document.addEventListener('visibilitychange', () => {
        if (document.hidden && this.active) {
          this.version++;
          this.release();
          this.message('页面已切到后台，摄像头已暂停。返回后请点击“打开摄像头”。');
        }
      });
    }

    message(text, error = false) {
      this.status.textContent = text;
      this.status.classList.toggle('is-error', error);
    }

    updateReady() {
      const ready = !!(this.active && this.stream && !this.pending && !this.capturing &&
        this.video.readyState >= 2 && this.video.videoWidth && this.video.videoHeight);
      this.captureButton.disabled = !ready;
      this.previewButton.disabled = !ready;
      this.placeholder.hidden = ready || !!this.stream;
    }

    release() {
      if (this.stream) this.stream.getTracks().forEach(track => track.stop());
      this.stream = null;
      this.video.pause();
      this.video.srcObject = null;
      this.pending = false;
      this.capturing = false;
      this.startButton.disabled = false;
      this.startButton.hidden = false;
      this.placeholder.hidden = false;
      this.devices.disabled = true;
      this.updateReady();
    }

    open() {
      if (this.active) return;
      this.active = true;
      this.root.hidden = false;
      this.callbacks.onOpen();
      this.start(this.devices.value);
    }

    close() {
      this.version++;
      this.listVersion++;
      this.release();
      this.active = false;
      this.root.hidden = true;
      this.callbacks.onClose();
    }

    async refreshDevices() {
      if (!this.active || !navigator.mediaDevices?.enumerateDevices) return;
      const version = this.version, listVersion = ++this.listVersion;
      try {
        const devices = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === 'videoinput');
        if (!this.active || version !== this.version || listVersion !== this.listVersion) return;
        const selected = this.stream?.getVideoTracks()[0]?.getSettings?.().deviceId || this.devices.value;
        const options = devices.map((d, i) => {
          const option = document.createElement('option');
          option.value = d.deviceId;
          option.textContent = d.label || '摄像头 ' + (i + 1);
          return option;
        });
        if (!options.length) {
          const option = document.createElement('option'); option.value = ''; option.textContent = '未找到摄像头'; options.push(option);
        }
        this.devices.replaceChildren(...options);
        if (devices.some(d => d.deviceId === selected)) this.devices.value = selected;
        this.devices.disabled = this.pending || this.capturing || !devices.length;
        if (!this.stream && !this.pending) {
          this.message(devices.length ? '已找到摄像头，请选择设备后打开。' : '未找到摄像头，请检查连接后刷新设备。');
        }
      } catch {
        if (version === this.version && this.active) this.message('暂时无法读取设备列表。可重新打开默认摄像头，或检查浏览器权限。', true);
      }
    }

    async start(deviceId = '') {
      if (!this.active) return;
      const version = ++this.version;
      this.release();
      if (!window.isSecureContext) {
        this.message('摄像头需要安全连接。请使用 HTTPS 网站，或在本机通过 localhost / 127.0.0.1 打开。', true);
        return;
      }
      if (!navigator.mediaDevices?.getUserMedia) {
        this.message('当前浏览器不支持网页摄像头。请用 Chrome、Edge 等浏览器打开本页，或继续上传图片。', true);
        return;
      }
      this.pending = true;
      this.startButton.disabled = true;
      this.message('正在打开摄像头，请在浏览器提示中允许访问。可以随时关闭或返回上传图片。');
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: false,
          video: {width: {ideal: 1920}, height: {ideal: 1080},
            ...(deviceId ? {deviceId: {exact: deviceId}} : {facingMode: {ideal: 'environment'}})}
        });
        if (!this.active || version !== this.version) {
          stream.getTracks().forEach(track => track.stop());
          return;
        }
        this.stream = stream;
        const track = stream.getVideoTracks()[0];
        track?.addEventListener('ended', () => {
          if (this.active && version === this.version) {
            this.version++;
            this.release();
            this.message('摄像头连接已断开，请重新连接设备并打开摄像头。', true);
            this.refreshDevices();
          }
        });
        this.video.srcObject = stream;
        await this.video.play();
        if (!this.active || version !== this.version) return;
        this.pending = false;
        this.startButton.hidden = true;
        this.message('摄像头已开启。将鸟放入画面，选择“拍照并识别”或先“拍照预览”。');
        this.updateReady();
        await this.refreshDevices();
      } catch (error) {
        if (!this.active || version !== this.version) return;
        this.release();
        this.message(cameraError(error), true);
      }
    }

    async capture(identify) {
      if (this.captureButton.disabled || !this.stream) return;
      const version = this.version;
      this.capturing = true;
      this.devices.disabled = true;
      this.updateReady();
      this.message('正在生成照片…');
      try {
        const file = await photograph(this.video);
        if (!this.active || version !== this.version) return;
        this.close();
        this.callbacks.onCapture(file, identify);
      } catch (error) {
        if (!this.active || version !== this.version) return;
        this.capturing = false;
        this.devices.disabled = !this.devices.options.length;
        this.updateReady();
        this.message(error.message || '拍照失败，请重新拍照。', true);
      }
    }
  }

  window.BirdCamera = BirdCamera;
})();
