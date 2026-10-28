"""Local integration fixture: synthetic cameras + mock classifier, no physical camera/API use.

Run: python tests/camera_preview.py
Open: http://127.0.0.1:5081/ (add ?camera_test=denied to test permission errors)
This fixture is never imported by the normal app.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DONGNIAO_API_KEY'] = ' '
import app as site
from flask import request, Response

site.real_mode = lambda: False

FIXTURE = r"""
(() => {
  const devices = new EventTarget();
  const inputs = [
    {kind: 'videoinput', deviceId: 'test-built-in', label: '模拟内置摄像头'},
    {kind: 'videoinput', deviceId: 'test-usb', label: '模拟 USB 摄像头'}
  ];
  devices.enumerateDevices = async () => inputs;
  devices.getUserMedia = async constraints => {
    if (new URLSearchParams(location.search).get('camera_test') === 'denied') {
      throw new DOMException('Synthetic denial', 'NotAllowedError');
    }
    const selected = constraints.video.deviceId?.exact || 'test-built-in';
    const canvas = document.createElement('canvas');
    canvas.width = 1280; canvas.height = 720;
    const ctx = canvas.getContext('2d');
    const image = new Image(); image.src = '/static/img/birds/oriental-stork.png';
    let frames = 0;
    const draw = () => {
      ctx.fillStyle = selected === 'test-usb' ? '#204c42' : '#263b59';
      ctx.fillRect(0, 0, 1280, 720);
      if (image.complete && image.naturalWidth) ctx.drawImage(image, 370, 90, 540, 540);
      ctx.fillStyle = '#ffffff'; ctx.font = '30px sans-serif';
      ctx.fillText('TEST CAMERA / ' + selected + ' / frame ' + frames++, 30, 45);
    };
    draw();
    const timer = setInterval(draw, 90);
    const stream = canvas.captureStream(12);
    const track = stream.getVideoTracks()[0];
    const settings = track.getSettings.bind(track);
    track.getSettings = () => ({...settings(), deviceId: selected});
    const stop = track.stop.bind(track);
    track.stop = () => { clearInterval(timer); stop(); };
    return stream;
  };
  Object.defineProperty(navigator, 'mediaDevices', {configurable: true, value: devices});
})();
"""


@site.app.route('/__camera_test__/fixture.js')
def fixture_js():
    return Response(FIXTURE, mimetype='application/javascript')


@site.app.after_request
def inject_test_camera(response):
    if request.path == '/' and response.status_code == 200:
        html = response.get_data(as_text=True)
        marker = '<script src="/static/js/camera.js"></script>'
        html = html.replace(marker, '<script src="/__camera_test__/fixture.js"></script>' + marker)
        html = html.replace('<h1>认识身边的飞鸟</h1>', '<h1>摄像头功能测试 · 模拟画面</h1>')
        response.set_data(html)
    return response


if __name__ == '__main__':
    site.app.run(host='127.0.0.1', port=5081, debug=False)
