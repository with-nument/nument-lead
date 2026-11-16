'use client'

// The sign-in art: a brushed silver Nument card and four glossy black coins, floating in soft studio light.
// Each coin is a black lacquer token with a thin polished chrome rim and a raised lowercase n on both faces
// (real extruded geometry with a small bevel, not a texture). The card is light brushed aluminium with the
// wordmark engraved in the corner.
//
// Framing: the camera's field of view is fitted to the panel on every resize, so the group always sits in
// the middle of the panel at the same proportions (card about 40% of the panel width) with clear margin on
// every side, whatever the window shape. Changing only the field of view scales the picture about its
// centre, so the poster (a still of the rest pose rendered at POSTER_ASPECT) lines up exactly when shown
// with object-fit: contain (auth-art.tsx).
//
// Motion: float, pointer tilt, hover spin (raycast), drag, spin-all on Continue and Sign in, and a short
// intro rise. Every spin eases back to an upright rest pose facing the camera (coins within about 30
// degrees), so a coin never rests edge-on or with its n upside down or mirrored. Reduced motion = still.
//
// It is loaded lazily after the page is up (src/components/auth/auth-art.tsx), so three.js is never part
// of the sign-in page's first load. The poster stays on screen until the first frame is drawn and stays for
// good if WebGL is not available.
//
// Colours here are scene data (material colours and canvas textures), so this file is the one exemption
// from the design lint (tests/unit/design-lint.test.ts).

import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js'
import { RoundedBoxGeometry } from 'three/examples/jsm/geometries/RoundedBoxGeometry.js'
import { SPIN_EVENT } from './spin'

/** Width / height of the poster images in public/auth/ (rendered from this scene at rest; auth-art.tsx). */
const POSTER_ASPECT = 1.2

// Framing, in world units on the z = 0 plane, seen from CAMERA_Z. The card is 3.4 wide, so a half width of
// 4.25 makes it 40% of the panel width; the group itself spans about 64% of that width, leaving margin for
// float, tilt, drag and the spin-all burst.
const CAMERA_Z = 11
const HALF_W = 4.25
const HALF_H = HALF_W / POSTER_ASPECT

const CARD_W = 3.4
const CARD_H = 2.15
const COIN_R = (CARD_H * 0.55) / 2 // each coin is about 0.55x the card height across
const COIN_T = 0.13
const TURN = Math.PI * 2

type Item = {
  /** Rest position, orientation and float; the spinner inside it turns about its own vertical axis. */
  holder: THREE.Group
  spinner: THREE.Group
  base: THREE.Vector3
  rot: THREE.Euler
  amp: number
  speed: number
  phase: number
  depth: number
  /** Spin angle and speed (radians, radians per second). */
  angle: number
  vel: number
  /** Rest angles are multiples of this: half a turn for coins (both faces carry the n), a full turn for the card. */
  step: number
  coin: boolean
}

type Props = {
  /** Called once, after the first frame is on the canvas. */
  onReady: () => void
  /** Called if the GPU drops the context; the poster comes back. */
  onLost?: () => void
  className?: string
}

/** The page font (Figtree, from next/font) as a canvas font family, read from the page. */
function fontFamily(el: HTMLElement) {
  const v = getComputedStyle(el).getPropertyValue('--nf-sans').trim()
  return v ? `${v}, sans-serif` : 'Figtree, sans-serif'
}

export default function CoinsScene({ onReady, onLost, className }: Props) {
  const hostRef = useRef<HTMLDivElement>(null)
  const readyRef = useRef(onReady)
  const lostRef = useRef(onLost)
  useEffect(() => {
    readyRef.current = onReady
    lostRef.current = onLost
  })

  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    let disposed = false
    let cleanup = () => {}

    // A fresh canvas per mount, so a remount (React strict mode, navigation) never reuses a dead context.
    const canvas = document.createElement('canvas')
    canvas.setAttribute('aria-hidden', 'true')
    canvas.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;display:block;cursor:grab;touch-action:pan-y'

    let renderer: THREE.WebGLRenderer
    try {
      renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true })
    } catch {
      return // No WebGL: the poster stays.
    }
    host.appendChild(canvas)

    const family = fontFamily(host)
    const fontsReady = document.fonts.load(`700 118px ${family}`).catch(() => [])

    void fontsReady.then(() => {
      if (disposed) return
      cleanup = start(renderer, canvas, host, family, {
        ready: () => readyRef.current(),
        lost: () => lostRef.current?.(),
      })
    })

    return () => {
      disposed = true
      cleanup()
      renderer.dispose()
      renderer.forceContextLoss() // frees the GPU context now rather than at garbage collection
      canvas.remove()
    }
  }, [])

  return <div ref={hostRef} className={className} />
}

/** A lowercase n (stem and arch, Figtree-like bold proportions), x-height `h`, centred on the origin. */
function letterN(h: number) {
  const sw = 0.21 // stem width
  const w = 0.82 // overall width
  const p = (x: number, y: number) => [(x - w / 2) * h, (y - 0.5) * h] as const
  const s = new THREE.Shape()
  s.moveTo(...p(0, 0))
  s.lineTo(...p(sw, 0))
  s.lineTo(...p(sw, 0.58))
  // inside of the arch
  s.bezierCurveTo(...p(sw + 0.01, 0.74), ...p(0.27, 0.81), ...p(0.41, 0.81))
  s.bezierCurveTo(...p(0.54, 0.81), ...p(w - sw, 0.75), ...p(w - sw, 0.6))
  s.lineTo(...p(w - sw, 0))
  s.lineTo(...p(w, 0))
  s.lineTo(...p(w, 0.64))
  // outside of the arch
  s.bezierCurveTo(...p(w, 0.9), ...p(0.69, 1.02), ...p(0.47, 1.02))
  s.bezierCurveTo(...p(0.33, 1.02), ...p(sw + 0.04, 0.96), ...p(sw, 0.87))
  s.lineTo(...p(sw, 1))
  s.lineTo(...p(0, 1))
  s.closePath()
  return s
}

/** Builds the scene and runs it. Returns the teardown. */
function start(
  renderer: THREE.WebGLRenderer,
  canvas: HTMLCanvasElement,
  host: HTMLElement,
  family: string,
  on: { ready: () => void; lost: () => void },
) {
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2))
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = 1.1
  const scene = new THREE.Scene()
  const pmrem = new THREE.PMREMGenerator(renderer)
  // The room, with its light panels turned down to soft boxes (at full strength a black coin turned towards
  // one reflects pure white), plus two soft boxes behind the camera, off to the sides, so the faces turned
  // towards the viewer show a soft studio sheen on one side while a coin facing straight on stays black.
  const room = new RoomEnvironment(renderer)
  room.traverse((o) => {
    if (o instanceof THREE.Mesh && o.material instanceof THREE.MeshBasicMaterial && o.material.color.r > 1) {
      o.material.color.setScalar(Math.min(o.material.color.r * 0.12, 4))
    }
  })
  const boxGeo = new THREE.BoxGeometry()
  const boxMats = [3, 2].map((v) => new THREE.MeshBasicMaterial({ color: new THREE.Color().setScalar(v) }))
  for (const [i, x, y, sx, sy] of [
    [0, -6, 5, 5, 3.5],
    [1, 8, -4, 3, 7],
  ] as const) {
    const box = new THREE.Mesh(boxGeo, boxMats[i])
    box.position.set(x, y, 13.8)
    box.scale.set(sx, sy, 0.1)
    room.add(box)
  }
  const envMap = pmrem.fromScene(room, 0.03).texture
  scene.environment = envMap
  const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 100)
  camera.position.set(0, 0, CAMERA_Z)

  // Soft studio light on top of the room reflections: a key from the upper left and a broad fill, so the
  // silver card stays light at every tilt. No floor and no cast shadows.
  const key = new THREE.DirectionalLight(0xffffff, 1.4)
  key.position.set(-4, 6, 8)
  const fill = new THREE.HemisphereLight(0xffffff, 0xd8d8dc, 1.1)
  scene.add(key, fill)

  // Canvas textures: brushed aluminium and the engraved wordmark (colour, and a height map for the cut).
  function tex(w: number, h: number, draw: (ctx: CanvasRenderingContext2D, w: number, h: number) => void, color = true) {
    const c = document.createElement('canvas')
    c.width = w
    c.height = h
    draw(c.getContext('2d')!, w, h)
    const t = new THREE.CanvasTexture(c)
    if (color) t.colorSpace = THREE.SRGBColorSpace
    t.anisotropy = 8
    return t
  }
  const brushLines = Array.from({ length: 3200 }, () => [Math.random(), Math.random() * 0.06, Math.random() > 0.5] as const)
  function brushed(ctx: CanvasRenderingContext2D, w: number, h: number, base: string) {
    ctx.fillStyle = base
    ctx.fillRect(0, 0, w, h)
    for (const [y, a, light] of brushLines) {
      ctx.fillStyle = light ? `rgba(255,255,255,${a})` : `rgba(0,0,0,${a * 0.8})`
      ctx.fillRect(0, y * h, w, 1)
    }
  }
  const wordmark = (ctx: CanvasRenderingContext2D, h: number) => {
    ctx.font = `700 118px ${family}`
    ctx.textBaseline = 'alphabetic'
    ctx.translate(78, h - 78)
  }
  const cardBack = tex(1024, 640, (ctx, w, h) => brushed(ctx, w, h, '#cdd0d3'))
  const cardFace = tex(1024, 640, (ctx, w, h) => {
    brushed(ctx, w, h, '#cdd0d3')
    wordmark(ctx, h)
    ctx.fillStyle = 'rgba(255,255,255,.7)' // the lit lower lip of the cut
    ctx.fillText('nument', 1.5, 2)
    ctx.fillStyle = 'rgba(92,94,99,.85)'
    ctx.fillText('nument', 0, 0)
  })
  const cardCut = tex(
    1024,
    640,
    (ctx, w, h) => {
      ctx.fillStyle = '#fff'
      ctx.fillRect(0, 0, w, h)
      wordmark(ctx, h)
      ctx.fillStyle = '#000'
      ctx.fillText('nument', 0, 0)
    },
    false,
  )

  const silver = new THREE.MeshPhysicalMaterial({
    color: 0xffffff,
    map: cardFace,
    bumpMap: cardCut,
    bumpScale: 1.2,
    metalness: 0.55,
    roughness: 0.36,
    clearcoat: 0.25,
    clearcoatRoughness: 0.3,
    envMapIntensity: 0.8,
  })
  const silverBack = silver.clone()
  silverBack.map = cardBack
  silverBack.bumpMap = null
  const silverEdge = new THREE.MeshPhysicalMaterial({ color: 0xdcdde0, metalness: 0.7, roughness: 0.28 })
  const lacquer = new THREE.MeshPhysicalMaterial({
    color: 0x08080a,
    metalness: 0,
    roughness: 0.2,
    envMapIntensity: 0.4, // a soft sheen, never a white coin when it turns into the soft box
    clearcoat: 1,
    clearcoatRoughness: 0.05,
  })
  const chrome = new THREE.MeshPhysicalMaterial({ color: 0xf4f4f6, metalness: 1, roughness: 0.1, side: THREE.DoubleSide })
  const letterEdge = new THREE.MeshPhysicalMaterial({ color: 0xececee, metalness: 1, roughness: 0.1, clearcoat: 1, clearcoatRoughness: 0.05 })

  // Coin geometry, axis along z (the front face looks at the camera at rest).
  const ri = COIN_R - 0.065 // where the black face meets the chrome rim
  const faceZ = COIN_T / 2 - 0.016
  const faceGeo = new THREE.CircleGeometry(ri + 0.002, 96)
  const rimProfile = [
    [ri, faceZ],
    [ri + 0.008, COIN_T / 2 - 0.002],
    [ri + 0.03, COIN_T / 2],
    [COIN_R - 0.022, COIN_T / 2 - 0.004],
    [COIN_R - 0.006, COIN_T / 2 - 0.02],
    [COIN_R, COIN_T / 2 - 0.042],
    [COIN_R, -(COIN_T / 2 - 0.042)],
    [COIN_R - 0.006, -(COIN_T / 2 - 0.02)],
    [COIN_R - 0.022, -(COIN_T / 2 - 0.004)],
    [ri + 0.03, -COIN_T / 2],
    [ri + 0.008, -(COIN_T / 2 - 0.002)],
    [ri, -faceZ],
  ].map(([r, y]) => new THREE.Vector2(r, y))
  const rimGeo = new THREE.LatheGeometry(rimProfile, 128)
  rimGeo.rotateX(Math.PI / 2) // lathe axis y -> z
  const bevel = 0.02
  const nGeo = new THREE.ExtrudeGeometry(letterN(COIN_R * 0.86), {
    depth: 0.022,
    bevelEnabled: true,
    bevelThickness: bevel,
    bevelSize: 0.016,
    bevelSegments: 4,
    curveSegments: 24,
  })
  nGeo.translate(0.012 * COIN_R, 0, bevel) // optical centring; the back of the bevel sits on z = 0

  function makeCoin() {
    const coin = new THREE.Group()
    coin.add(new THREE.Mesh(rimGeo, chrome))
    for (const side of [1, -1]) {
      // The back is the front turned half a turn about the vertical axis, so either face reads upright.
      const face = new THREE.Group()
      face.rotation.y = side === 1 ? 0 : Math.PI
      const disc = new THREE.Mesh(faceGeo, lacquer)
      disc.position.z = faceZ
      const n = new THREE.Mesh(nGeo, [lacquer, letterEdge]) // caps black, bevel and walls catch the light
      n.position.z = faceZ - 0.002
      face.add(disc, n)
      coin.add(face)
    }
    return coin
  }

  const world = new THREE.Group()
  scene.add(world)
  const items: Item[] = []
  function place(obj: THREE.Object3D, o: { pos: [number, number, number]; rot: [number, number, number]; amp: number; speed: number; coin: boolean }) {
    const holder = new THREE.Group()
    const spinner = new THREE.Group()
    spinner.add(obj)
    holder.add(spinner)
    holder.rotation.set(...o.rot)
    world.add(holder)
    items.push({
      holder,
      spinner,
      base: new THREE.Vector3(...o.pos),
      rot: holder.rotation.clone(),
      amp: o.amp,
      speed: o.speed,
      phase: Math.random() * 6,
      depth: 1 + o.pos[2] * 0.4,
      angle: 0,
      vel: 0,
      step: o.coin ? Math.PI : TURN,
      coin: o.coin,
    })
  }

  // The silver card
  const cardGeo = new RoundedBoxGeometry(CARD_W, CARD_H, 0.07, 6, 0.12)
  const cardFaceGeo = new THREE.PlaneGeometry(CARD_W - 0.15, CARD_H - 0.13)
  const card = new THREE.Mesh(cardGeo, silverEdge)
  const face = new THREE.Mesh(cardFaceGeo, silver)
  face.position.z = 0.0365
  const back = new THREE.Mesh(cardFaceGeo, silverBack)
  back.position.z = -0.0365
  back.rotation.y = Math.PI
  card.add(face, back)
  place(card, { pos: [-0.05, 0.05, 0], rot: [-0.16, 0.26, 0.4], amp: 0.08, speed: 0.6, coin: false })

  // Four black coins around it: rest poses within about 30 degrees of facing the camera, small in-plane roll.
  const spots: [number, number, number, number, number, number][] = [
    [-1.9, 1.45, 0.55, 0.26, 0.38, -0.1],
    [1.45, 1.88, -0.35, 0.3, -0.34, 0.12],
    [1.98, -0.6, 0.65, -0.18, -0.42, 0.08],
    [-1.2, -1.92, 0.45, -0.3, 0.3, -0.12],
  ]
  const coinNodes: THREE.Object3D[] = []
  for (const [x, y, z, rx, ry, rz] of spots) {
    const coin = makeCoin()
    coinNodes.push(coin)
    place(coin, { pos: [x, y, z], rot: [rx, ry, rz], amp: 0.1, speed: 0.8 + Math.random() * 0.4, coin: true })
  }
  const coinItems = items.filter((i) => i.coin)

  // Interaction: tilt toward the pointer, hover spins a coin, drag turns the scene, Continue spins everything.
  const pointer = new THREE.Vector2()
  const target = new THREE.Vector2()
  const ray = new THREE.Raycaster()
  let dragging = false
  let dragX = 0
  let dragRot = 0
  let dragVel = 0
  let burst = 0
  let intro = reduce ? 1 : 0

  const onMove = (e: PointerEvent) => {
    target.set((e.clientX / innerWidth) * 2 - 1, -(e.clientY / innerHeight) * 2 + 1)
    if (dragging) {
      dragVel = (e.clientX - dragX) * 0.008
      dragRot += dragVel
      dragX = e.clientX
    }
    const r = canvas.getBoundingClientRect()
    pointer.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1)
    ray.setFromCamera(pointer, camera)
    const hit = ray.intersectObjects(coinNodes, true)[0]
    if (hit) {
      const it = coinItems.find((i) => {
        let o: THREE.Object3D | null = hit.object
        while (o && o !== i.spinner) o = o.parent
        return !!o
      })
      if (it) it.vel = Math.max(it.vel, 9)
    }
    canvas.style.cursor = dragging ? 'grabbing' : hit ? 'pointer' : 'grab'
  }
  const onDown = (e: PointerEvent) => {
    dragging = true
    dragX = e.clientX
    canvas.setPointerCapture(e.pointerId)
  }
  const onUp = () => {
    dragging = false
  }
  const spinAll = () => {
    burst = 1
    for (const i of items) i.vel = Math.max(i.vel, 19) // about one full turn each
  }
  addEventListener('pointermove', onMove)
  addEventListener('pointerup', onUp)
  addEventListener(SPIN_EVENT, spinAll)
  canvas.addEventListener('pointerdown', onDown)

  // Fit the framing rectangle to the panel: whichever of width and height is tighter sets the field of view.
  function resize() {
    const r = host.getBoundingClientRect()
    if (!r.width || !r.height) return
    renderer.setSize(r.width, r.height, false)
    camera.aspect = r.width / r.height
    const half = Math.max(HALF_H, HALF_W / camera.aspect)
    camera.fov = THREE.MathUtils.radToDeg(2 * Math.atan(half / CAMERA_Z))
    camera.updateProjectionMatrix()
  }
  const sizer = new ResizeObserver(resize)
  sizer.observe(host)
  resize()

  /** Eases a spin to rest: free spin while fast, then a spring to the nearest rest angle. */
  function settle(it: Item, dt: number) {
    it.vel *= Math.exp(-dt * 2.6)
    it.angle += it.vel * dt
    const rest = Math.round(it.angle / it.step) * it.step
    const pull = THREE.MathUtils.clamp(1 - Math.abs(it.vel) / 3, 0, 1)
    it.angle += (rest - it.angle) * (1 - Math.exp(-dt * 5)) * pull
  }

  // Time only moves while frames are drawn, so a paused scene picks up where it stopped.
  const clock = new THREE.Clock()
  let t = 0
  let first = true
  function frame() {
    const dt = Math.min(clock.getDelta(), 0.05)
    t += dt
    intro = Math.min(1, intro + dt * 0.75)
    const ease = 1 - Math.pow(1 - intro, 3)
    const m = reduce ? 0 : 1
    if (!dragging) {
      dragVel *= Math.exp(-dt * 4)
      dragRot += dragVel
      // drifts back to the nearest whole turn, so the scene always comes back facing the camera
      const home = Math.round(dragRot / TURN) * TURN
      const pull = THREE.MathUtils.clamp(1 - Math.abs(dragVel) * 20, 0, 1)
      dragRot += (home - dragRot) * (1 - Math.exp(-dt * 2.5)) * pull
    }
    burst *= Math.exp(-dt * 2.5)
    const k = 1 - Math.exp(-dt * 4)
    world.rotation.y += (target.x * 0.3 * m + dragRot - world.rotation.y) * k
    world.rotation.x += (-target.y * 0.18 * m - world.rotation.x) * k
    const spread = 1 + burst * 0.1
    for (const it of items) {
      it.holder.position.set(
        it.base.x * spread + target.x * 0.15 * it.depth * m,
        it.base.y * spread + Math.sin(t * it.speed + it.phase) * it.amp * m - (1 - ease) * 1.2 * it.depth,
        it.base.z,
      )
      it.holder.rotation.set(
        it.rot.x + Math.sin(t * 0.5 + it.phase) * 0.07 * m,
        it.rot.y + Math.sin(t * 0.33 + it.phase) * 0.08 * m,
        it.rot.z + Math.cos(t * 0.4 + it.phase) * 0.05 * m,
      )
      settle(it, dt)
      // the intro turns each coin in once and lands on the rest pose
      it.spinner.rotation.y = it.angle + (it.coin ? (1 - ease) * TURN : 0)
    }
    renderer.render(scene, camera)
    if (first) {
      first = false
      on.ready()
    }
  }

  // Runs only while the tab is visible and the art is on screen (phones scroll it away).
  let raf = 0
  let onScreen = true
  const loop = () => {
    frame()
    raf = requestAnimationFrame(loop)
  }
  const sync = () => {
    const run = onScreen && document.visibilityState === 'visible'
    if (run && !raf) {
      clock.getDelta() // drop the time spent paused
      raf = requestAnimationFrame(loop)
    } else if (!run && raf) {
      cancelAnimationFrame(raf)
      raf = 0
    }
  }
  const seen = new IntersectionObserver(([entry]) => {
    onScreen = entry?.isIntersecting ?? true
    sync()
  })
  seen.observe(host)
  document.addEventListener('visibilitychange', sync)
  const onLost = (e: Event) => {
    e.preventDefault()
    on.lost()
  }
  canvas.addEventListener('webglcontextlost', onLost)
  sync()

  return () => {
    cancelAnimationFrame(raf)
    raf = 0
    seen.disconnect()
    sizer.disconnect()
    document.removeEventListener('visibilitychange', sync)
    removeEventListener('pointermove', onMove)
    removeEventListener('pointerup', onUp)
    removeEventListener(SPIN_EVENT, spinAll)
    canvas.removeEventListener('pointerdown', onDown)
    canvas.removeEventListener('webglcontextlost', onLost)
    for (const g of [cardGeo, cardFaceGeo, faceGeo, rimGeo, nGeo]) g.dispose()
    for (const x of [silver, silverBack, silverEdge, lacquer, chrome, letterEdge]) x.dispose()
    for (const x of [cardFace, cardBack, cardCut, envMap]) x.dispose()
    room.dispose()
    boxGeo.dispose()
    for (const x of boxMats) x.dispose()
    pmrem.dispose()
    renderer.renderLists.dispose()
  }
}
