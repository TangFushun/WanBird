const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '../public/static/js/camera.js'), 'utf8');
const settle = () => new Promise(resolve => setImmediate(resolve));

class Element extends EventTarget {
  constructor() {
    super(); this.disabled = false; this.hidden = false; this.children = [];
    this.value = ''; this.textContent = ''; this.classes = new Set();
    this.classList = {toggle: (name, value) => value ? this.classes.add(name) : this.classes.delete(name)};
  }
  replaceChildren(...children) { this.children = children; this.value = children[0]?.value || ''; }
  get options() { return this.children; }
}

function stream(id) {
  const track = new EventTarget();
  track.stopped = false;
  track.stop = () => { track.stopped = true; };
  track.getSettings = () => ({deviceId: id});
  return {track, getTracks: () => [track], getVideoTracks: () => [track]};
}

function setup({media, encodeSizes = [1000], secure = true, width = 1920, height = 1080} = {}) {
  const ids = ['cameraVideo','cameraDevice','cameraStatus','cameraPlaceholder','cameraStart',
    'cameraCapture','cameraPreview','cameraRefresh','cameraClose'];
  const elements = Object.fromEntries(ids.map(id => [id, new Element()]));
  const video = elements.cameraVideo;
  Object.assign(video, {readyState: 2, videoWidth: width, videoHeight: height,
    srcObject: null, play: async () => {}, pause() {}});
  const calls = [], frames = [], encodings = [], events = [], streams = [];
  const devices = new EventTarget();
  devices.getUserMedia = media || (async constraints => {
    calls.push(constraints);
    const s = stream(constraints.video.deviceId?.exact || 'built-in'); streams.push(s); return s;
  });
  devices.enumerateDevices = async () => [
    {kind: 'videoinput', label: '内置摄像头', deviceId: 'built-in'},
    {kind: 'audioinput', label: '麦克风', deviceId: 'mic'},
    {kind: 'videoinput', label: 'USB 摄像头', deviceId: 'usb'}
  ];
  const doc = new EventTarget();
  doc.hidden = false;
  doc.createElement = tag => {
    if (tag !== 'canvas') return new Element();
    const canvas = {width: 0, height: 0};
    canvas.getContext = () => ({drawImage: (...args) => frames.push(args)});
    canvas.toBlob = (callback, type, quality) => {
      encodings.push({type, quality, width: canvas.width, height: canvas.height});
      const size = encodeSizes.length > 1 ? encodeSizes.shift() : encodeSizes[0];
      setImmediate(() => callback(size === null ? null : new Blob([new Uint8Array(size)], {type})));
    };
    return canvas;
  };
  const win = new EventTarget(); win.isSecureContext = secure;
  const context = vm.createContext({window: win, document: doc, navigator: {mediaDevices: devices}, File, Blob, Date});
  vm.runInContext(source, context);
  const root = new Element(); root.querySelector = selector => elements[selector.slice(1)];
  const camera = new win.BirdCamera(root, {
    onOpen: () => events.push(['open']), onClose: () => events.push(['close']),
    onCapture: (file, identify) => events.push(['capture', file, identify])
  });
  return {camera, root, elements, video, devices, doc, win, calls, frames, encodings, events, streams};
}

test('lists only video devices, requests no audio, and switches to the exact USB device', async () => {
  const s = setup(); s.camera.open(); await settle();
  assert.equal(s.calls[0].audio, false);
  assert.deepEqual(s.elements.cameraDevice.options.map(d => d.textContent), ['内置摄像头','USB 摄像头']);
  assert.equal(s.elements.cameraCapture.disabled, false);
  await s.camera.start('usb');
  assert.equal(s.streams[0].track.stopped, true);
  assert.equal(s.calls[1].video.deviceId.exact, 'usb');
  assert.equal(s.elements.cameraDevice.value, 'usb');
  s.camera.close(); assert.equal(s.streams[1].track.stopped, true);
});

test('permission granted after closing cannot reopen or leak a camera stream', async () => {
  let grant;
  const s = setup({media: () => new Promise(resolve => { grant = resolve; })});
  s.camera.open(); s.camera.close();
  const late = stream('late'); grant(late); await settle();
  assert.equal(late.track.stopped, true);
  assert.equal(s.video.srcObject, null); assert.equal(s.root.hidden, true);
});

test('an older pending camera request cannot replace a newer USB stream', async () => {
  let grant;
  const usb = stream('usb'); let count = 0;
  const s = setup({media: () => ++count === 1 ? new Promise(resolve => { grant = resolve; }) : Promise.resolve(usb)});
  s.camera.open(); await s.camera.start('usb');
  const late = stream('built-in'); grant(late); await settle();
  assert.equal(late.track.stopped, true); assert.equal(s.video.srcObject, usb);
  assert.equal(usb.track.stopped, false); s.camera.close();
});

test('denied permission, missing and busy devices give useful errors and permit retry', async () => {
  for (const [name, text] of [['NotAllowedError','权限'],['NotFoundError','没有找到'],['NotReadableError','占用'],['OverconstrainedError','刷新设备']]) {
    const s = setup({media: async () => { throw Object.assign(new Error(), {name}); }});
    s.camera.open(); await settle();
    assert.match(s.elements.cameraStatus.textContent, new RegExp(text));
    assert.equal(s.elements.cameraStart.disabled, false);
    assert.equal(s.elements.cameraCapture.disabled, true);
    assert.equal(s.video.srcObject, null);
  }
});

test('insecure connections do not request device permissions', async () => {
  const s = setup({secure: false}); s.camera.open(); await settle();
  assert.equal(s.calls.length, 0); assert.match(s.elements.cameraStatus.textContent, /HTTPS/);
});

test('capture freezes a proportional frame, compresses under 2MB, stops camera, and requests recognition', async () => {
  const s = setup({width: 3840, height: 2160, encodeSizes: [3*1024*1024, 2*1024*1024+1, 1500]});
  s.camera.open(); await settle(); await s.camera.capture(true);
  const capture = s.events.find(e => e[0] === 'capture');
  assert.ok(capture[1] instanceof File); assert.equal(capture[1].type, 'image/jpeg');
  assert.ok(capture[1].size <= 2*1024*1024); assert.equal(capture[2], true);
  assert.equal(s.frames[0][3], 1600); assert.equal(s.frames[0][4], 900);
  assert.equal(s.frames.filter(f => f[0] === s.video).length, 1);
  assert.equal(s.encodings.length, 3); assert.equal(s.streams[0].track.stopped, true);
  assert.equal(s.root.hidden, true);
});

test('capture for preview does not request recognition', async () => {
  const s = setup(); s.camera.open(); await settle(); await s.camera.capture(false);
  assert.equal(s.events.find(e => e[0] === 'capture')[2], false);
});

test('no photo can be taken before video frames arrive', async () => {
  const s = setup({width: 0, height: 0}); s.camera.open(); await settle();
  await s.camera.capture(true);
  assert.equal(s.elements.cameraCapture.disabled, true);
  assert.equal(s.events.some(e => e[0] === 'capture'), false); s.camera.close();
});

test('failed JPEG encoding leaves the camera open for another attempt', async () => {
  const s = setup({encodeSizes: [null]}); s.camera.open(); await settle(); await s.camera.capture(true);
  assert.match(s.elements.cameraStatus.textContent, /照片生成失败/);
  assert.equal(s.elements.cameraCapture.disabled, false);
  assert.equal(s.streams[0].track.stopped, false); s.camera.close();
});

test('closing during JPEG encoding discards the pending photo', async () => {
  const s = setup(); s.camera.open(); await settle();
  const result = s.camera.capture(true); s.camera.close(); await result;
  assert.equal(s.events.some(e => e[0] === 'capture'), false);
  assert.equal(s.streams[0].track.stopped, true);
});

test('backgrounding or leaving the page releases camera tracks', async () => {
  const s = setup(); s.camera.open(); await settle();
  s.doc.hidden = true; s.doc.dispatchEvent(new Event('visibilitychange'));
  assert.equal(s.streams[0].track.stopped, true);
  assert.equal(s.elements.cameraCapture.disabled, true);
  assert.match(s.elements.cameraStatus.textContent, /后台/);
  s.doc.hidden = false; await s.camera.start();
  s.win.dispatchEvent(new Event('pagehide'));
  assert.equal(s.streams[1].track.stopped, true); assert.equal(s.root.hidden, true);
});

test('disconnecting a camera disables capture and frees the ended stream', async () => {
  const s = setup(); s.camera.open(); await settle();
  s.streams[0].track.dispatchEvent(new Event('ended')); await settle();
  assert.equal(s.video.srcObject, null); assert.equal(s.elements.cameraCapture.disabled, true);
  assert.equal(s.elements.cameraStart.hidden, false);
});
