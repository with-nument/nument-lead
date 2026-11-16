'use client'

// The sign-in art: a brushed silver Nument card and four black coins, floating in soft light.
// Ported one to one from the approved mock (signin-spec.html, three@0.160.0): same geometry,
// materials, canvas textures, lights, camera, float, cursor tilt, hover spin (raycast), drag,
// spin-all on Continue and Sign in, the intro fly-in, and reduced motion = still.
//
// It is loaded with next/dynamic after the page is up (src/components/auth/auth-art.tsx), so three.js
// is never part of the sign-in page's first load. The poster stays on screen until the first frame is
// drawn and stays for good if WebGL is not available.
//
// Colours here are scene data (material colours and canvas textures), so this file is the one exemption
// from the design lint (tests/unit/design-lint.test.ts).

import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js'
import { RoundedBoxGeometry } from 'three/examples/jsm/geometries/RoundedBoxGeometry.js'
import { SPIN_EVENT } from './spin'

type Item = {
  obj: THREE.Mesh
  base: THREE.Vector3
  rot: THREE.Euler
  amp: number
  speed: number
  phase: number
  depth: number
  spin: number
  coin?: boolean
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
    const fontsReady = Promise.all([document.fonts.load(`700 120px ${family}`), document.fonts.load(`700 300px ${family}`)]).catch(() => [])

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
  renderer.toneMappingExposure = 1.05
  renderer.shadowMap.enabled = true
  renderer.shadowMap.type = THREE.PCFSoftShadowMap
  const scene = new THREE.Scene()
  const pmrem = new THREE.PMREMGenerator(renderer)
  const room = new RoomEnvironment()
  const envMap = pmrem.fromScene(room, 0.04).texture
  scene.environment = envMap
  const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 100)
  camera.position.set(0, 0, 11)

  const key = new THREE.DirectionalLight(0xffffff, 1.6)
  key.position.set(-4, 6, 7)
  key.castShadow = true
  key.shadow.mapSize.set(1024, 1024)
  key.shadow.radius = 8
  Object.assign(key.shadow.camera, { left: -6, right: 6, top: 6, bottom: -6 })
  scene.add(key, new THREE.AmbientLight(0xffffff, 0.35))
  const floorGeo = new THREE.PlaneGeometry(30, 30)
  const floorMat = new THREE.ShadowMaterial({ opacity: 0.12 })
  const floor = new THREE.Mesh(floorGeo, floorMat)
  floor.rotation.x = -Math.PI / 2
  floor.position.y = -3.4
  floor.receiveShadow = true
  scene.add(floor)

  // Canvas textures: brushed metal, the engraved wordmark and the embossed n.
  function tex(w: number, h: number, draw: (ctx: CanvasRenderingContext2D, w: number, h: number) => void) {
    const c = document.createElement('canvas')
    c.width = w
    c.height = h
    draw(c.getContext('2d')!, w, h)
    const t = new THREE.CanvasTexture(c)
    t.colorSpace = THREE.SRGBColorSpace
    t.anisotropy = 8
    return t
  }
  function brushed(ctx: CanvasRenderingContext2D, w: number, h: number, base: string) {
    ctx.fillStyle = base
    ctx.fillRect(0, 0, w, h)
    for (let i = 0; i < 2600; i++) {
      const y = Math.random() * h
      const a = Math.random() * 0.07
      ctx.fillStyle = Math.random() > 0.5 ? `rgba(255,255,255,${a})` : `rgba(0,0,0,${a})`
      ctx.fillRect(0, y, w, 1)
    }
  }
  const cardFace = tex(1024, 640, (ctx, w, h) => {
    brushed(ctx, w, h, '#b9bbbe')
    ctx.font = `700 120px ${family}`
    ctx.textBaseline = 'alphabetic'
    ctx.save()
    ctx.translate(80, h - 90)
    ctx.fillStyle = 'rgba(255,255,255,.55)'
    ctx.fillText('nument', 2, 2)
    ctx.fillStyle = 'rgba(40,40,44,.55)'
    ctx.fillText('nument', 0, 0)
    ctx.restore()
  })
  const coinFace = tex(512, 512, (ctx, w, h) => {
    const g = ctx.createRadialGradient(w * 0.4, h * 0.35, 20, w / 2, h / 2, w / 2)
    g.addColorStop(0, '#3a3a3d')
    g.addColorStop(1, '#141416')
    ctx.fillStyle = g
    ctx.fillRect(0, 0, w, h)
    ctx.strokeStyle = 'rgba(255,255,255,.18)'
    ctx.lineWidth = 10
    ctx.beginPath()
    ctx.arc(w / 2, h / 2, w * 0.4, 0, Math.PI * 2)
    ctx.stroke()
    ctx.font = `700 300px ${family}`
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillStyle = 'rgba(0,0,0,.6)'
    ctx.fillText('n', w / 2 + 6, h / 2 - 14)
    ctx.fillStyle = '#4a4a4e'
    ctx.fillText('n', w / 2, h / 2 - 20)
  })
  const silver = new THREE.MeshPhysicalMaterial({ color: 0xffffff, map: cardFace, metalness: 0.85, roughness: 0.32, clearcoat: 0.4 })
  const silverEdge = new THREE.MeshPhysicalMaterial({ color: 0xc8c9cc, metalness: 1, roughness: 0.25 })
  const blackSide = new THREE.MeshPhysicalMaterial({ color: 0x1b1b1d, metalness: 0.9, roughness: 0.28, clearcoat: 0.6 })
  const blackFace = new THREE.MeshPhysicalMaterial({ map: coinFace, metalness: 0.75, roughness: 0.35, clearcoat: 0.8, clearcoatRoughness: 0.2 })

  const world = new THREE.Group()
  scene.add(world)
  const items: Item[] = []
  // The silver card
  const cardGeo = new RoundedBoxGeometry(3.4, 2.15, 0.07, 6, 0.12)
  const faceGeo = new THREE.PlaneGeometry(3.25, 2.02)
  const card = new THREE.Mesh(cardGeo, silverEdge)
  const face = new THREE.Mesh(faceGeo, silver)
  face.position.z = 0.0365
  card.add(face)
  card.castShadow = true
  card.rotation.set(-0.25, 0.35, 0.62)
  world.add(card)
  items.push({ obj: card, base: new THREE.Vector3(0.1, -0.1, 0), rot: card.rotation.clone(), amp: 0.12, speed: 0.6, phase: 0, depth: 0.5, spin: 0 })
  // Four black coins
  const coinGeo = new THREE.CylinderGeometry(0.62, 0.62, 0.16, 96)
  const spots = [
    [-1.6, 1.55, 0.6, 0.9, -0.5],
    [1.15, 2.35, -0.4, 1.1, 0.4],
    [1.75, -0.45, 1.0, 0.8, -0.3],
    [0.65, -2.45, 0.3, 1.25, 0.6],
  ] as const
  for (const [x, y, z, rx, rz] of spots) {
    const coin = new THREE.Mesh(coinGeo, [blackSide, blackFace, blackFace])
    coin.castShadow = true
    coin.rotation.set(rx, 0.3, rz)
    world.add(coin)
    items.push({
      obj: coin,
      base: new THREE.Vector3(x, y, z),
      rot: coin.rotation.clone(),
      amp: 0.18,
      speed: 0.8 + Math.random() * 0.4,
      phase: Math.random() * 6,
      depth: 1 + z * 0.4,
      spin: 0,
      coin: true,
    })
  }
  const coins = items.filter((i) => i.coin).map((i) => i.obj)

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
    const hit = ray.intersectObjects(coins, true)[0]
    if (hit) {
      const it = items.find((i) => i.obj === hit.object || i.obj === hit.object.parent)
      if (it) it.spin = Math.max(it.spin, 9)
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
    items.forEach((i) => (i.spin = Math.max(i.spin, i.coin ? 18 : 3)))
  }
  addEventListener('pointermove', onMove)
  addEventListener('pointerup', onUp)
  addEventListener(SPIN_EVENT, spinAll)
  canvas.addEventListener('pointerdown', onDown)

  function resize() {
    const r = host.getBoundingClientRect()
    if (!r.width || !r.height) return
    renderer.setSize(r.width, r.height, false)
    camera.aspect = r.width / r.height
    camera.updateProjectionMatrix()
  }
  const sizer = new ResizeObserver(resize)
  sizer.observe(host)
  resize()

  // Time only moves while frames are drawn, so a paused scene picks up where it stopped.
  const clock = new THREE.Clock()
  let t = 0
  let first = true
  function frame() {
    const dt = Math.min(clock.getDelta(), 0.05)
    t += dt
    intro = Math.min(1, intro + dt * 0.7)
    const ease = 1 - Math.pow(1 - intro, 3)
    if (!dragging) {
      dragVel *= 0.94
      dragRot += dragVel
    }
    dragRot *= 0.985 // drifts back to rest
    burst *= 0.96
    world.rotation.y += (target.x * 0.35 + dragRot - world.rotation.y) * 0.06
    world.rotation.x += (-target.y * 0.2 - world.rotation.x) * 0.06
    for (const it of items) {
      const m = reduce ? 0 : 1
      const fly = (1 - ease) * 6 * it.depth
      it.obj.position.set(
        it.base.x * (1 + burst * 0.35) + target.x * 0.25 * it.depth,
        it.base.y * (1 + burst * 0.35) + Math.sin(t * it.speed + it.phase) * it.amp * m - fly,
        it.base.z,
      )
      it.spin *= 0.95
      it.obj.rotation.x = it.rot.x + Math.sin(t * 0.5 + it.phase) * 0.08 * m
      it.obj.rotation.z = it.rot.z + Math.cos(t * 0.4 + it.phase) * 0.06 * m
      it.obj.rotation.y += it.spin * dt + 0.12 * dt * m * (it.coin ? 1 : 0.2)
      if (!it.coin) it.obj.rotation.y += (it.rot.y + Math.sin(t * 0.3) * 0.15 - it.obj.rotation.y) * 0.03
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
  cardFace.needsUpdate = coinFace.needsUpdate = true
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
    for (const g of [floorGeo, cardGeo, faceGeo, coinGeo]) g.dispose()
    for (const m of [floorMat, silver, silverEdge, blackSide, blackFace]) m.dispose()
    for (const x of [cardFace, coinFace, envMap]) x.dispose()
    room.dispose()
    pmrem.dispose()
    key.shadow.map?.dispose()
    renderer.renderLists.dispose()
  }
}
