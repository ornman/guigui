(function (global, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (global) global.XiaojiangMotion = api.XiaojiangMotion;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const SVG_NS = 'http://www.w3.org/2000/svg';
  const STATES = [
    'idle', 'reading', 'thinking', 'complete', 'angry',
    'alarm', 'loading', 'ingesting', 'diagnosing', 'sleep',
  ];
  let instanceCounter = 0;

  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
  const random = (min, max) => min + Math.random() * (max - min);

  function spring(value = 0) {
    return { value, velocity: 0, target: value };
  }

  function stepSpring(item, stiffness, damping, dt) {
    const acceleration = (item.target - item.value) * stiffness - item.velocity * damping;
    item.velocity += acceleration * dt;
    item.value += item.velocity * dt;
    if (!Number.isFinite(item.value) || !Number.isFinite(item.velocity)) {
      item.value = item.target;
      item.velocity = 0;
    }
  }

  function blinkValue(elapsed, duration = 230) {
    if (elapsed < 0 || elapsed > duration) return 1;
    const progress = elapsed / duration;
    const closure = Math.sin(Math.PI * progress) ** 2;
    return 1 - closure * 0.94;
  }

  function poseAt(state, time, stateElapsed) {
    if (state === 'reading') {
    return {
      x: 0.8 * Math.sin(time * 2.1),
      y: 1.6 * Math.sin(time * 3.6),
      rotation: -1.8 + 1.2 * Math.sin(time * 1.4),
      scaleX: 1,
      scaleY: 1 - 0.012 * Math.max(0, Math.sin(time * 3.6)),
      gazeX: 5.4 * Math.sin(time * 1.25),
      gazeY: 3.6,
        happy: 0,
      };
    }
    if (state === 'thinking') {
      return {
        x: 1.2 * Math.sin(time * 0.9),
        y: -1.5 + 2 * Math.sin(time * 1.35),
        rotation: -4.5 + 2 * Math.sin(time * 0.72),
        scaleX: 1,
        scaleY: 1,
        gazeX: -3.6 + 1.8 * Math.sin(time * 0.8),
        gazeY: -4.2,
        happy: 0,
      };
    }
    if (state === 'angry') {
      return {
        x: 0.25 * Math.sin(time * 0.9),
        y: 0.65 * Math.sin(time * 1.4),
        rotation: 0,
        scaleX: 1,
        scaleY: 1,
        gazeX: 0,
        gazeY: 0,
        happy: 0,
      };
    }
    if (state === 'alarm') {
      const progress = clamp(stateElapsed / 0.62, 0, 1);
      const pop = Math.sin(progress * Math.PI);
      return {
        x: 0,
        y: -3.8 * pop,
        rotation: 0,
        scaleX: 1 + 0.035 * pop,
        scaleY: 1 + 0.035 * pop,
        gazeX: 0,
        gazeY: -0.5,
        happy: 0,
      };
    }
    if (state === 'loading') {
      return {
        x: 0,
        y: 0.7 * Math.sin(time * 2.4),
        rotation: 0,
        scaleX: 1,
        scaleY: 1,
        gazeX: 0,
        gazeY: 0,
        happy: 0,
      };
    }
    if (state === 'ingesting') {
      return {
        x: 0.5 * Math.sin(time * 1.7),
        y: 1.2 * Math.sin(time * 2.1),
        rotation: 0.8 * Math.sin(time * 1.3),
        scaleX: 1,
        scaleY: 1,
        gazeX: 0,
        gazeY: 0,
        happy: 0,
      };
    }
    if (state === 'diagnosing') {
      return {
        x: 0,
        y: 0.55 * Math.sin(time * 2.2),
        rotation: 0,
        scaleX: 1,
        scaleY: 1,
        gazeX: 0,
        gazeY: 0,
        happy: 0,
      };
    }
    if (state === 'sleep') {
      return {
        x: 0.3 * Math.sin(time * 0.55),
        y: 1.5 + 1.25 * Math.sin(time * 0.9),
        rotation: -2.5 + 0.35 * Math.sin(time * 0.65),
        scaleX: 1 + 0.006 * Math.sin(time * 0.9),
        scaleY: 1 - 0.012 * Math.sin(time * 0.9),
        gazeX: 0,
        gazeY: 0,
        happy: 0,
      };
    }
    if (state === 'complete') {
      const progress = clamp(stateElapsed / 0.72, 0, 1);
      const hop = Math.sin(progress * Math.PI);
      return {
        x: 0,
        y: -9.5 * hop,
        rotation: 3.5 * Math.sin(progress * Math.PI * 2) * (1 - progress),
        scaleX: 1 - 0.055 * hop,
        scaleY: 1 + 0.075 * hop,
        gazeX: 0,
        gazeY: 0,
        happy: 1,
      };
    }
    return {
      x: 1.2 * Math.sin(time * 0.92) + 0.4 * Math.sin(time * 2.2),
      y: 1.7 * Math.sin(time * 1.55),
      rotation: 1.45 * Math.sin(time * 0.63),
      scaleX: 1 + 0.008 * Math.sin(time * 1.55),
      scaleY: 1 - 0.015 * Math.sin(time * 1.55),
      gazeX: 0,
      gazeY: 0,
      happy: 0,
    };
  }

  function svgElement(name, attributes = {}) {
    const element = document.createElementNS(SVG_NS, name);
    Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
    return element;
  }

  class XiaojiangMotion {
    constructor(host, options = {}) {
      if (!host) throw new Error('XiaojiangMotion requires a host element');
      this.host = host;
      this.options = {
        size: options.size || 64,
        state: options.state || 'idle',
        faceTop: options.faceTop || '#294c78',
        faceBottom: options.faceBottom || '#152a48',
        eyes: options.eyes || '#eaf7ff',
        pulse: options.pulse || '#75e3b0',
        followPointer: options.followPointer !== false,
        motionScale: clamp(Number(options.motionScale ?? 1), 0.5, 2),
        respectReducedMotion: options.respectReducedMotion !== false,
      };
      this.state = this.options.state;
      this.reducedMotion = this.options.respectReducedMotion && typeof matchMedia === 'function'
        && matchMedia('(prefers-reduced-motion: reduce)').matches;
      this.startedAt = performance.now();
      this.stateStartedAt = this.startedAt;
      this.lastAt = this.startedAt;
      // Let the first blink happen quickly so a newly opened assistant feels alive.
      this.nextBlinkAt = this.startedAt + random(550, 1050);
      this.blinkStartedAt = -Infinity;
      this.secondBlinkAt = -Infinity;
      this.nextGazeAt = this.startedAt + random(900, 1900);
      this.autoGaze = { x: 0, y: 0 };
      this.pointerGaze = null;
      this.raf = 0;

      this.motion = {
        x: spring(0),
        y: spring(0),
        rotation: spring(0),
        scaleX: spring(1),
        scaleY: spring(1),
        gazeX: spring(0),
        gazeY: spring(0),
        happy: spring(this.state === 'complete' ? 1 : 0),
        angry: spring(this.state === 'angry' ? 1 : 0),
        alarm: spring(this.state === 'alarm' ? 1 : 0),
        loading: spring(this.state === 'loading' ? 1 : 0),
        ingesting: spring(this.state === 'ingesting' ? 1 : 0),
        diagnosing: spring(this.state === 'diagnosing' ? 1 : 0),
        sleep: spring(this.state === 'sleep' ? 1 : 0),
      };

      this._build();
      this._paint(this.startedAt);
      if (!this.reducedMotion) this.raf = requestAnimationFrame((time) => this._tick(time));
    }

    _build() {
      const id = ++instanceCounter;
      const svg = svgElement('svg', {
        viewBox: '0 0 128 128',
        width: this.options.size,
        height: this.options.size,
        role: 'img',
        'aria-label': '小匠文档助手',
      });
      svg.style.display = 'block';
      svg.style.overflow = 'visible';

      const defs = svgElement('defs');
      const gradient = svgElement('linearGradient', {
        id: `xiaojiang-face-${id}`,
        x1: '0',
        y1: '0',
        x2: '0',
        y2: '1',
      });
      gradient.append(
        svgElement('stop', { offset: '0%', 'stop-color': this.options.faceTop }),
        svgElement('stop', { offset: '100%', 'stop-color': this.options.faceBottom }),
      );
      defs.appendChild(gradient);

      const group = svgElement('g');
      const faceGroup = svgElement('g', { 'data-role': 'face' });
      const face = svgElement('path', {
        d: 'M28 29C38 18 89 17 101 29C113 41 114 84 103 98C92 112 37 111 26 98C16 85 17 41 28 29Z',
        fill: `url(#xiaojiang-face-${id})`,
      });
      const leftEye = svgElement('ellipse', { cx: '47', cy: '66', rx: '6.7', ry: '9.1', fill: this.options.eyes });
      const rightEye = svgElement('ellipse', { cx: '81', cy: '66', rx: '6.7', ry: '9.1', fill: this.options.eyes });
      const leftHappy = svgElement('path', {
        d: 'M38 69Q47 58 56 69',
        fill: 'none',
        stroke: this.options.eyes,
        'stroke-width': '5.5',
        'stroke-linecap': 'round',
        opacity: '0',
        'data-role': 'happy-eye',
      });
      const rightHappy = svgElement('path', {
        d: 'M72 69Q81 58 90 69',
        fill: 'none',
        stroke: this.options.eyes,
        'stroke-width': '5.5',
        'stroke-linecap': 'round',
        opacity: '0',
        'data-role': 'happy-eye',
      });
      const pulse = svgElement('path', {
        d: 'M84 33H88L90 26L93 39L96 29L99 33H104',
        fill: 'none',
        stroke: this.options.pulse,
        'stroke-width': '2.8',
        'stroke-linecap': 'round',
        'stroke-linejoin': 'round',
      });

      const alarmGroup = svgElement('g', { opacity: '0', 'data-role': 'alarm-symbol' });
      const alarmStroke = svgElement('path', {
        d: 'M64 43V72', fill: 'none', stroke: this.options.eyes,
        'stroke-width': '10', 'stroke-linecap': 'round',
      });
      const alarmDot = svgElement('circle', { cx: '64', cy: '86', r: '5.5', fill: this.options.eyes });
      alarmGroup.append(alarmStroke, alarmDot);

      const loadingGroup = svgElement('g', { opacity: '0', 'data-role': 'loading-symbol' });
      const loadingOuter = svgElement('circle', {
        cx: '64', cy: '64', r: '29', fill: 'none', stroke: this.options.faceTop,
        'stroke-width': '10', 'stroke-linecap': 'round', 'stroke-dasharray': '76 108',
      });
      const loadingInner = svgElement('circle', {
        cx: '64', cy: '64', r: '16', fill: 'none', stroke: this.options.pulse,
        'stroke-width': '6', 'stroke-linecap': 'round', 'stroke-dasharray': '31 70',
      });
      const loadingDot = svgElement('circle', { cx: '64', cy: '64', r: '4.5', fill: this.options.eyes });
      loadingGroup.append(loadingOuter, loadingInner, loadingDot);

      const ingestGroup = svgElement('g', { opacity: '0', 'data-role': 'ingesting-symbol' });
      const documentBack = svgElement('rect', {
        x: '38', y: '34', width: '38', height: '49', rx: '6', fill: this.options.faceBottom, opacity: '.56',
      });
      const documentMiddle = svgElement('rect', {
        x: '48', y: '34', width: '38', height: '50', rx: '6', fill: this.options.faceTop, opacity: '.78',
      });
      const documentFront = svgElement('rect', {
        x: '43', y: '42', width: '43', height: '51', rx: '7', fill: this.options.faceTop,
        'data-role': 'document-stack',
      });
      const ingestLines = [0, 1, 2].map((index) => svgElement('path', {
        d: `M52 ${58 + index * 10}H${index === 2 ? 70 : 78}`,
        fill: 'none', stroke: index === 0 ? this.options.pulse : this.options.eyes,
        'stroke-width': index === 0 ? '4' : '3', 'stroke-linecap': 'round', opacity: index === 0 ? '1' : '.78',
      }));
      const ingestParticles = Array.from({ length: 7 }, (_, index) => svgElement('circle', {
        cx: '64', cy: '64', r: index % 3 === 0 ? '2.7' : '2.1',
        fill: index % 2 === 0 ? this.options.pulse : this.options.eyes,
        'data-role': 'ingest-particle',
      }));
      ingestGroup.append(documentBack, documentMiddle, documentFront, ...ingestLines, ...ingestParticles);

      const diagnosticGroup = svgElement('g', { opacity: '0', 'data-role': 'diagnostic-symbol' });
      const diagnosticBaseline = svgElement('path', {
        d: 'M33 66H95', fill: 'none', stroke: this.options.eyes,
        'stroke-width': '1.5', opacity: '.18', 'stroke-linecap': 'round',
      });
      const diagnosticWave = svgElement('path', {
        d: 'M33 66H95', fill: 'none', stroke: this.options.pulse,
        'stroke-width': '3.3', 'stroke-linecap': 'round', 'stroke-linejoin': 'round',
        'data-role': 'diagnostic-wave',
      });
      const diagnosticScan = svgElement('circle', {
        cx: '33', cy: '66', r: '3.2', fill: this.options.eyes,
        'data-role': 'diagnostic-scan',
      });
      diagnosticGroup.append(diagnosticBaseline, diagnosticWave, diagnosticScan);

      const sleepGroup = svgElement('g', { opacity: '0', 'data-role': 'sleep-symbol' });
      const leftSleep = svgElement('path', {
        d: 'M38 65Q47 72 56 65', fill: 'none', stroke: this.options.eyes,
        'stroke-width': '5', 'stroke-linecap': 'round',
      });
      const rightSleep = svgElement('path', {
        d: 'M72 65Q81 72 90 65', fill: 'none', stroke: this.options.eyes,
        'stroke-width': '5', 'stroke-linecap': 'round',
      });
      const sleepZSmall = svgElement('path', {
        d: 'M89 45H99L89 55H99', fill: 'none', stroke: this.options.pulse,
        'stroke-width': '3.2', 'stroke-linecap': 'round', 'stroke-linejoin': 'round',
      });
      const sleepZLarge = svgElement('path', {
        d: 'M96 25H109L96 38H109', fill: 'none', stroke: this.options.eyes,
        'stroke-width': '4', 'stroke-linecap': 'round', 'stroke-linejoin': 'round',
      });
      sleepGroup.append(leftSleep, rightSleep, sleepZSmall, sleepZLarge);

      faceGroup.append(face, leftEye, rightEye, leftHappy, rightHappy, pulse);
      group.append(faceGroup, alarmGroup, diagnosticGroup, sleepGroup, loadingGroup, ingestGroup);
      svg.append(defs, group);
      this.host.replaceChildren(svg);

      this.svg = svg;
      this.group = group;
      this.faceGroup = faceGroup;
      this.leftEye = leftEye;
      this.rightEye = rightEye;
      this.leftHappy = leftHappy;
      this.rightHappy = rightHappy;
      this.pulse = pulse;
      this.alarmGroup = alarmGroup;
      this.alarmStroke = alarmStroke;
      this.alarmDot = alarmDot;
      this.loadingGroup = loadingGroup;
      this.loadingInner = loadingInner;
      this.loadingDot = loadingDot;
      this.ingestGroup = ingestGroup;
      this.documentBack = documentBack;
      this.documentMiddle = documentMiddle;
      this.documentFront = documentFront;
      this.ingestLines = ingestLines;
      this.ingestParticles = ingestParticles;
      this.diagnosticGroup = diagnosticGroup;
      this.diagnosticWave = diagnosticWave;
      this.diagnosticScan = diagnosticScan;
      this.sleepGroup = sleepGroup;
      this.sleepZSmall = sleepZSmall;
      this.sleepZLarge = sleepZLarge;
    }

    setState(state) {
      if (!STATES.includes(state)) return;
      this.state = state;
      const labels = {
        idle: '小匠文档助手，待命', reading: '小匠正在阅读', thinking: '小匠正在思考',
        complete: '小匠已完成', angry: '小匠有点生气', alarm: '小匠发出报警',
        loading: '小匠正在加载', ingesting: '小匠正在加载大量资料',
        diagnosing: '小匠正在诊断振动信号', sleep: '小匠正在睡觉',
      };
      this.svg.setAttribute('aria-label', labels[state]);
      this.stateStartedAt = performance.now();
      this.motion.happy.target = state === 'complete' ? 1 : 0;
      this.motion.angry.target = state === 'angry' ? 1 : 0;
      this.motion.alarm.target = state === 'alarm' ? 1 : 0;
      this.motion.loading.target = state === 'loading' ? 1 : 0;
      this.motion.ingesting.target = state === 'ingesting' ? 1 : 0;
      this.motion.diagnosing.target = state === 'diagnosing' ? 1 : 0;
      this.motion.sleep.target = state === 'sleep' ? 1 : 0;
      if (this.reducedMotion) {
        const pose = poseAt(state, 0, 1);
        Object.keys(this.motion).forEach((key) => {
          this.motion[key].value = pose[key] ?? this.motion[key].target;
          this.motion[key].target = this.motion[key].value;
          this.motion[key].velocity = 0;
        });
        this._paint(performance.now());
      }
    }

    setGaze(normalizedX, normalizedY) {
      if (!this.options.followPointer || this.reducedMotion) return;
      this.pointerGaze = {
        x: clamp(normalizedX, -1, 1) * 7.5,
        y: clamp(normalizedY, -1, 1) * 5,
      };
    }

    clearGaze() {
      this.pointerGaze = null;
    }

    destroy() {
      cancelAnimationFrame(this.raf);
      this.host.replaceChildren();
    }

    _blinkOpen(now) {
      let open = blinkValue(now - this.blinkStartedAt);
      if (Number.isFinite(this.secondBlinkAt)) open = Math.min(open, blinkValue(now - this.secondBlinkAt));
      return open;
    }

    _updateBlink(now) {
      if (now < this.nextBlinkAt) return;
      this.blinkStartedAt = now;
      this.secondBlinkAt = Math.random() < 0.16 ? now + 310 : -Infinity;
      this.nextBlinkAt = now + random(2600, 6500);
    }

    _updateAutonomousGaze(now) {
      if (now < this.nextGazeAt || this.pointerGaze || this.state !== 'idle') return;
      this.autoGaze = { x: random(-2.6, 2.6), y: random(-1.6, 1.6) };
      this.nextGazeAt = now + random(1400, 3300);
    }

    _tick(now) {
      const dt = Math.min((now - this.lastAt) / 1000, 0.05);
      this.lastAt = now;
      this._updateBlink(now);
      this._updateAutonomousGaze(now);

      const time = (now - this.startedAt) / 1000;
      const elapsed = (now - this.stateStartedAt) / 1000;
      const pose = poseAt(this.state, time, elapsed);
      const canFollowPointer = this.state === 'idle' || this.state === 'reading' || this.state === 'thinking';
      const gaze = canFollowPointer ? (this.pointerGaze || (this.state === 'idle' ? this.autoGaze : null)) : null;
      const amount = this.options.motionScale;

      this.motion.x.target = pose.x * amount;
      this.motion.y.target = pose.y * amount;
      this.motion.rotation.target = pose.rotation * amount;
      this.motion.scaleX.target = 1 + (pose.scaleX - 1) * amount;
      this.motion.scaleY.target = 1 + (pose.scaleY - 1) * amount;
      this.motion.gazeX.target = gaze ? gaze.x : pose.gazeX * amount;
      this.motion.gazeY.target = gaze ? gaze.y : pose.gazeY * amount;
      this.motion.happy.target = pose.happy;
      this.motion.angry.target = this.state === 'angry' ? 1 : 0;
      this.motion.alarm.target = this.state === 'alarm' ? 1 : 0;
      this.motion.loading.target = this.state === 'loading' ? 1 : 0;
      this.motion.ingesting.target = this.state === 'ingesting' ? 1 : 0;
      this.motion.diagnosing.target = this.state === 'diagnosing' ? 1 : 0;
      this.motion.sleep.target = this.state === 'sleep' ? 1 : 0;

      const steps = Math.max(1, Math.ceil(dt / (1 / 120)));
      const step = dt / steps;
      for (let index = 0; index < steps; index += 1) {
        stepSpring(this.motion.x, 95, 16, step);
        stepSpring(this.motion.y, 95, 16, step);
        stepSpring(this.motion.rotation, 82, 15, step);
        stepSpring(this.motion.scaleX, 120, 18, step);
        stepSpring(this.motion.scaleY, 120, 18, step);
        stepSpring(this.motion.gazeX, 145, 19, step);
        stepSpring(this.motion.gazeY, 145, 19, step);
        stepSpring(this.motion.happy, 135, 20, step);
        stepSpring(this.motion.angry, 150, 21, step);
        stepSpring(this.motion.alarm, 165, 22, step);
        stepSpring(this.motion.loading, 110, 18, step);
        stepSpring(this.motion.ingesting, 110, 18, step);
        stepSpring(this.motion.diagnosing, 125, 19, step);
        stepSpring(this.motion.sleep, 105, 18, step);
      }

      this._paint(now);
      this.raf = requestAnimationFrame((timeNow) => this._tick(timeNow));
    }

    _paint(now) {
      const motion = this.motion;
      this.group.setAttribute(
        'transform',
        `translate(${(64 + motion.x.value).toFixed(2)} ${(64 + motion.y.value).toFixed(2)}) `
          + `rotate(${motion.rotation.value.toFixed(2)}) `
          + `scale(${motion.scaleX.value.toFixed(4)} ${motion.scaleY.value.toFixed(4)}) translate(-64 -64)`,
      );

      const happy = clamp(motion.happy.value, 0, 1);
      const angry = clamp(motion.angry.value, 0, 1);
      const alarm = clamp(motion.alarm.value, 0, 1);
      const loading = clamp(motion.loading.value, 0, 1);
      const ingesting = clamp(motion.ingesting.value, 0, 1);
      const diagnosing = clamp(motion.diagnosing.value, 0, 1);
      const sleeping = clamp(motion.sleep.value, 0, 1);
      const symbolMix = clamp(loading + ingesting, 0, 1);
      const blink = this.state === 'complete' ? 1 : this._blinkOpen(now);
      const eyeOpacity = 1 - clamp(Math.max(happy, alarm, diagnosing, sleeping), 0, 1);
      const eyeY = 66 + motion.gazeY.value;
      const eyeOpen = Math.max(0.05, blink);
      const eyeScale = 1 + 0.025 * Math.sin((now - this.startedAt) / 520);
      const leftX = 47 + motion.gazeX.value;
      const rightX = 81 + motion.gazeX.value;
      const eyeRadiusX = 6.7 * eyeScale * (1 - angry) + 5.3 * angry;
      const eyeRadiusY = 9.1 * eyeOpen * (1 - angry) + 11.8 * angry;

      this.leftEye.setAttribute('cx', leftX.toFixed(2));
      this.rightEye.setAttribute('cx', rightX.toFixed(2));
      this.leftEye.setAttribute('cy', eyeY.toFixed(2));
      this.rightEye.setAttribute('cy', eyeY.toFixed(2));
      this.leftEye.setAttribute('rx', eyeRadiusX.toFixed(2));
      this.rightEye.setAttribute('rx', eyeRadiusX.toFixed(2));
      this.leftEye.setAttribute('ry', eyeRadiusY.toFixed(2));
      this.rightEye.setAttribute('ry', eyeRadiusY.toFixed(2));
      this.leftEye.setAttribute('transform', `rotate(${(-38 * angry).toFixed(2)} ${leftX.toFixed(2)} ${eyeY.toFixed(2)})`);
      this.rightEye.setAttribute('transform', `rotate(${(38 * angry).toFixed(2)} ${rightX.toFixed(2)} ${eyeY.toFixed(2)})`);
      this.leftEye.setAttribute('opacity', eyeOpacity.toFixed(3));
      this.rightEye.setAttribute('opacity', eyeOpacity.toFixed(3));
      this.leftHappy.setAttribute('opacity', happy.toFixed(3));
      this.rightHappy.setAttribute('opacity', happy.toFixed(3));
      this.faceGroup.setAttribute('opacity', (1 - symbolMix).toFixed(3));

      const activePulse = this.state === 'reading' || this.state === 'thinking';
      const pulseAlpha = activePulse ? 0.78 + 0.22 * Math.sin(now / 180) : 1;
      const pulseVisibility = 1 - clamp(Math.max(alarm, diagnosing, sleeping), 0, 1);
      this.pulse.setAttribute('opacity', (pulseAlpha * pulseVisibility).toFixed(3));
      this.pulse.setAttribute('stroke', this.options.pulse);
      this.pulse.setAttribute('stroke-dasharray', activePulse ? '7 5' : 'none');
      this.pulse.setAttribute('stroke-dashoffset', activePulse ? String(-(now / 42) % 24) : '0');

      const alarmScale = 0.82 + alarm * 0.18 + 0.018 * alarm * Math.sin(now / 170);
      this.alarmGroup.setAttribute('opacity', alarm.toFixed(3));
      this.alarmGroup.setAttribute(
        'transform',
        `translate(64 64) scale(${alarmScale.toFixed(3)}) translate(-64 -64)`,
      );

      const sampleCount = 48;
      const wavePhase = now / 82;
      const waveY = (sample) => {
        const envelope = 0.62 + 0.38 * Math.sin(Math.PI * sample / sampleCount);
        return 66 + envelope * (5.2 * Math.sin(sample * 1.45 + wavePhase)
          + 2.1 * Math.sin(sample * 3.7 - wavePhase * 1.35));
      };
      const wavePoints = Array.from({ length: sampleCount + 1 }, (_, index) => {
        const x = 33 + (62 * index / sampleCount);
        return `${index === 0 ? 'M' : 'L'}${x.toFixed(2)} ${waveY(index).toFixed(2)}`;
      });
      this.diagnosticWave.setAttribute('d', wavePoints.join(''));
      this.diagnosticGroup.setAttribute('opacity', diagnosing.toFixed(3));
      const scanPhase = (now / 1380) % 1;
      const scanSample = scanPhase * sampleCount;
      this.diagnosticScan.setAttribute('cx', (33 + 62 * scanPhase).toFixed(2));
      this.diagnosticScan.setAttribute('cy', waveY(scanSample).toFixed(2));

      this.sleepGroup.setAttribute('opacity', sleeping.toFixed(3));
      const smallZPhase = (now / 1550) % 1;
      const largeZPhase = ((now / 1550) + 0.46) % 1;
      this.sleepZSmall.setAttribute('opacity', Math.sin(Math.PI * smallZPhase).toFixed(3));
      this.sleepZLarge.setAttribute('opacity', Math.sin(Math.PI * largeZPhase).toFixed(3));
      this.sleepZSmall.setAttribute('transform', `translate(0 ${(-10 * smallZPhase).toFixed(2)})`);
      this.sleepZLarge.setAttribute('transform', `translate(0 ${(-13 * largeZPhase).toFixed(2)})`);

      const loadingAngle = (now / 4.8) % 360;
      const loadingScale = 0.78 + loading * 0.22;
      this.loadingGroup.setAttribute('opacity', loading.toFixed(3));
      this.loadingGroup.setAttribute(
        'transform',
        `translate(64 64) rotate(${loadingAngle.toFixed(2)}) scale(${loadingScale.toFixed(3)}) translate(-64 -64)`,
      );
      this.loadingInner.setAttribute('transform', `rotate(${(-loadingAngle * 2.2).toFixed(2)} 64 64)`);
      this.loadingDot.setAttribute('r', (4.2 + 1.2 * Math.sin(now / 150)).toFixed(2));

      const ingestAngle = 1.6 * Math.sin(now / 370);
      const ingestScale = 0.82 + ingesting * 0.18;
      this.ingestGroup.setAttribute('opacity', ingesting.toFixed(3));
      this.ingestGroup.setAttribute(
        'transform',
        `translate(64 64) rotate(${ingestAngle.toFixed(2)}) scale(${ingestScale.toFixed(3)}) translate(-64 -64)`,
      );
      this.documentBack.setAttribute('transform', `rotate(${(-10 + 2.2 * Math.sin(now / 260)).toFixed(2)} 57 58)`);
      this.documentMiddle.setAttribute('transform', `rotate(${(8 + 2 * Math.sin(now / 310)).toFixed(2)} 67 59)`);
      this.ingestLines.forEach((line, index) => {
        line.setAttribute('stroke-dasharray', index === 0 ? '11 6' : 'none');
        line.setAttribute('stroke-dashoffset', index === 0 ? String(-(now / 55) % 17) : '0');
      });
      this.ingestParticles.forEach((particle, index) => {
        const phase = ((now / 960) + index / this.ingestParticles.length) % 1;
        const radius = 47 * (1 - phase);
        const angle = index * 2.399 + 0.45 * Math.sin(now / 520 + index);
        particle.setAttribute('cx', (64 + Math.cos(angle) * radius).toFixed(2));
        particle.setAttribute('cy', (64 + Math.sin(angle) * radius).toFixed(2));
        particle.setAttribute('opacity', Math.sin(Math.PI * phase).toFixed(3));
      });
    }
  }

  return { XiaojiangMotion, STATES, spring, stepSpring, blinkValue, poseAt };
});
