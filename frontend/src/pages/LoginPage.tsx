/**
 * @Date: 2026-05-30
 * @Author: xisy
 * @Discription: EduWeave 入口页，用户确认后创建演示会话并进入工作台。
 */
import { useGSAP } from "@gsap/react";
import { useMutation } from "@tanstack/react-query";
import gsap from "gsap";
import { Loader2 } from "lucide-react";
import { useRef } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { BrandWordmark } from "../components/BrandWordmark";
import { api } from "../lib/api";
import { useAuthStore } from "../stores/auth";

gsap.registerPlugin(useGSAP);

const techStack = [
  { name: "MinerU", icon: "/assets/landing/tech/mineru.svg" },
  { name: "Model Gateway", icon: "/assets/landing/tech/model-gateway.svg" },
  { name: "Milvus", icon: "/assets/landing/tech/milvus.svg" },
  { name: "Celery", icon: "/assets/landing/tech/celery.svg" },
  { name: "Raccoon PPT", icon: "/assets/landing/tech/raccoon-ppt.svg" },
  { name: "OBS", icon: "/assets/landing/tech/obs.svg" },
];

function ProductDemo() {
  return (
    <div className="relative hidden w-full items-start justify-end overflow-visible pt-14 lg:flex xl:-mr-4 xl:pt-16 2xl:-mr-8">
      <img
        className="relative z-10 w-full max-w-[1040px] object-contain xl:max-w-[1120px] 2xl:max-w-[1180px]"
        src="/assets/landing/eduweave-product-demo.png"
        alt="EduWeave 开始备课产品演示：上传教材 PDF 和学情 DOCX，生成课程大纲、教案、PPT课件、配套测练、作业与覆盖报告"
      />
    </div>
  );
}

type WeavePointer = {
  strength: number;
  x: number;
  y: number;
};

type WeaveStrand = {
  amplitude: number;
  baseY: number;
  glowOpacity: number;
  glowWidth: number;
  key: string;
  opacity: number;
  phase: number;
  pull: number;
  ripple: number;
  stroke: string;
  strokeWidth: number;
};

const weaveViewBoxWidth = 1000;
const weaveViewBoxHeight = 260;
const initialWeavePointer: WeavePointer = {
  strength: 0,
  x: weaveViewBoxWidth * 0.5,
  y: weaveViewBoxHeight * 0.58,
};
const weaveSampleXs = [-150, -30, 95, 220, 345, 470, 595, 720, 845, 970, 1090, 1150];
const weaveStrands: WeaveStrand[] = [
  {
    key: "teal-primary",
    baseY: 116,
    amplitude: 16,
    phase: 0.2,
    pull: 0.32,
    ripple: 13,
    stroke: "url(#weaveTeal)",
    strokeWidth: 1.25,
    glowWidth: 18,
    opacity: 0.82,
    glowOpacity: 0.4,
  },
  {
    key: "amber-primary",
    baseY: 166,
    amplitude: 18,
    phase: 1.25,
    pull: 0.26,
    ripple: -11,
    stroke: "url(#weaveAmber)",
    strokeWidth: 1.1,
    glowWidth: 17,
    opacity: 0.78,
    glowOpacity: 0.34,
  },
  {
    key: "teal-shadow",
    baseY: 142,
    amplitude: 12,
    phase: 2.2,
    pull: -0.18,
    ripple: 9,
    stroke: "url(#weaveTealSoft)",
    strokeWidth: 0.8,
    glowWidth: 11,
    opacity: 0.56,
    glowOpacity: 0.2,
  },
  {
    key: "amber-thread",
    baseY: 198,
    amplitude: 13,
    phase: 3.1,
    pull: 0.22,
    ripple: -8,
    stroke: "url(#weaveAmberSoft)",
    strokeWidth: 0.8,
    glowWidth: 12,
    opacity: 0.5,
    glowOpacity: 0.18,
  },
  {
    key: "ink-thread",
    baseY: 96,
    amplitude: 10,
    phase: 4.0,
    pull: -0.14,
    ripple: 7,
    stroke: "url(#weaveInk)",
    strokeWidth: 0.65,
    glowWidth: 8,
    opacity: 0.36,
    glowOpacity: 0.12,
  },
];

function smoothPath(points: Array<{ x: number; y: number }>) {
  const [firstPoint] = points;

  if (!firstPoint) {
    return "";
  }

  let path = `M ${firstPoint.x.toFixed(1)} ${firstPoint.y.toFixed(1)}`;

  for (let index = 0; index < points.length - 1; index += 1) {
    const previous = points[index - 1] ?? points[index];
    const current = points[index];
    const next = points[index + 1];
    const afterNext = points[index + 2] ?? next;
    const controlOneX = current.x + (next.x - previous.x) / 6;
    const controlOneY = current.y + (next.y - previous.y) / 6;
    const controlTwoX = next.x - (afterNext.x - current.x) / 6;
    const controlTwoY = next.y - (afterNext.y - current.y) / 6;

    path += ` C ${controlOneX.toFixed(1)} ${controlOneY.toFixed(1)}, ${controlTwoX.toFixed(1)} ${controlTwoY.toFixed(1)}, ${next.x.toFixed(1)} ${next.y.toFixed(1)}`;
  }

  return path;
}

function buildWeavePath(strand: WeaveStrand, pointer: WeavePointer, time: number) {
  const points = weaveSampleXs.map((x) => {
    const broadWave = Math.sin(x * 0.008 + strand.phase + time * 0.22) * strand.amplitude;
    const fineWave = Math.sin(x * 0.017 - strand.phase * 1.6 - time * 0.16) * strand.amplitude * 0.34;
    const baseY = strand.baseY + broadWave + fineWave;
    const distanceX = x - pointer.x;
    const influence = Math.exp(-(distanceX * distanceX) / (2 * 150 * 150)) * pointer.strength;
    const pullY = (pointer.y - baseY) * strand.pull * influence;
    const weaveRipple = Math.sin(distanceX * 0.045 + time * 2.2 + strand.phase) * strand.ripple * influence;

    return {
      x,
      y: baseY + pullY + weaveRipple,
    };
  });

  return smoothPath(points);
}

function FlowRibbon() {
  const ribbonRef = useRef<SVGSVGElement>(null);
  const strandRefs = useRef<Array<SVGPathElement | null>>([]);
  const glowRefs = useRef<Array<SVGPathElement | null>>([]);
  const gestureGlowRef = useRef<SVGGElement | null>(null);

  useGSAP(
    (_, contextSafe) => {
      const mm = gsap.matchMedia();

      mm.add("(prefers-reduced-motion: reduce)", () => {
        weaveStrands.forEach((strand, index) => {
          const path = buildWeavePath(strand, initialWeavePointer, 0);
          strandRefs.current[index]?.setAttribute("d", path);
          glowRefs.current[index]?.setAttribute("d", path);
        });
        gsap.set(gestureGlowRef.current, { autoAlpha: 0 });
      });

      mm.add("(prefers-reduced-motion: no-preference)", () => {
        const ribbon = ribbonRef.current;
        const gestureGlow = gestureGlowRef.current;

        if (!ribbon || !gestureGlow) {
          return;
        }

        const pointer = {
          strength: 0,
          targetStrength: 0,
          targetX: weaveViewBoxWidth * 0.5,
          targetY: weaveViewBoxHeight * 0.58,
          x: weaveViewBoxWidth * 0.5,
          y: weaveViewBoxHeight * 0.58,
        };
        const pathTargets = [...strandRefs.current, ...glowRefs.current].filter((node): node is SVGPathElement => Boolean(node));

        gsap.set(pathTargets, {
          willChange: "opacity",
        });
        gsap.set(gestureGlow, {
          autoAlpha: 0,
          transformOrigin: "50% 50%",
          willChange: "transform, opacity",
          x: pointer.x,
          y: pointer.y,
        });

        const renderWeave = () => {
          pointer.x += (pointer.targetX - pointer.x) * 0.1;
          pointer.y += (pointer.targetY - pointer.y) * 0.1;
          pointer.strength += (pointer.targetStrength - pointer.strength) * 0.08;

          const time = gsap.ticker.time;

          weaveStrands.forEach((strand, index) => {
            const path = buildWeavePath(strand, pointer, time);
            strandRefs.current[index]?.setAttribute("d", path);
            glowRefs.current[index]?.setAttribute("d", path);
          });

          gsap.set(gestureGlow, {
            autoAlpha: pointer.strength * 0.72,
            scaleX: 0.85 + pointer.strength * 0.42,
            scaleY: 0.72 + pointer.strength * 0.2,
            x: pointer.x,
            y: pointer.y,
          });
        };

        const followGesture = (event: PointerEvent) => {
          const progressX = gsap.utils.clamp(0, 1, event.clientX / window.innerWidth);
          const progressY = gsap.utils.clamp(0, 1, event.clientY / window.innerHeight);

          pointer.targetX = progressX * weaveViewBoxWidth;
          pointer.targetY = 58 + progressY * 176;
          pointer.targetStrength = event.pointerType === "touch" ? 0.78 : 1;
        };
        const settleGesture = () => {
          pointer.targetStrength = 0;
          pointer.targetY = weaveViewBoxHeight * 0.58;
        };

        const handlePointerMove = contextSafe ? contextSafe(followGesture) : followGesture;
        const handlePointerLeave = contextSafe ? contextSafe(settleGesture) : settleGesture;

        gsap.ticker.add(renderWeave);
        window.addEventListener("pointermove", handlePointerMove, { passive: true });
        window.addEventListener("pointerdown", handlePointerMove, { passive: true });
        window.addEventListener("pointerup", handlePointerLeave);
        window.addEventListener("pointercancel", handlePointerLeave);
        window.addEventListener("blur", handlePointerLeave);
        document.documentElement.addEventListener("pointerleave", handlePointerLeave);

        return () => {
          gsap.ticker.remove(renderWeave);
          window.removeEventListener("pointermove", handlePointerMove);
          window.removeEventListener("pointerdown", handlePointerMove);
          window.removeEventListener("pointerup", handlePointerLeave);
          window.removeEventListener("pointercancel", handlePointerLeave);
          window.removeEventListener("blur", handlePointerLeave);
          document.documentElement.removeEventListener("pointerleave", handlePointerLeave);
        };
      });

      return () => mm.revert();
    },
    { scope: ribbonRef },
  );

  return (
    <svg
      ref={ribbonRef}
      className="pointer-events-none absolute -bottom-8 left-1/2 hidden w-[calc(100vw+560px)] min-w-[1500px] max-w-none -translate-x-1/2 overflow-visible text-[#19796D] lg:block xl:-bottom-12 2xl:min-w-[1780px]"
      viewBox={`0 0 ${weaveViewBoxWidth} ${weaveViewBoxHeight}`}
      preserveAspectRatio="none"
      fill="none"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="weaveTeal" x1="-100" x2="1100" y1="0" y2="0" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#19796D" stopOpacity="0" />
          <stop offset="0.14" stopColor="#19796D" stopOpacity="0.34" />
          <stop offset="0.5" stopColor="#7ED3C8" stopOpacity="0.44" />
          <stop offset="0.86" stopColor="#19796D" stopOpacity="0.3" />
          <stop offset="1" stopColor="#19796D" stopOpacity="0" />
        </linearGradient>
        <linearGradient id="weaveAmber" x1="-100" x2="1100" y1="0" y2="0" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#D5A44A" stopOpacity="0" />
          <stop offset="0.16" stopColor="#D5A44A" stopOpacity="0.26" />
          <stop offset="0.52" stopColor="#F3D48B" stopOpacity="0.42" />
          <stop offset="0.86" stopColor="#D5A44A" stopOpacity="0.25" />
          <stop offset="1" stopColor="#D5A44A" stopOpacity="0" />
        </linearGradient>
        <linearGradient id="weaveTealSoft" x1="-100" x2="1100" y1="0" y2="0" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#7ED3C8" stopOpacity="0" />
          <stop offset="0.42" stopColor="#2E9E92" stopOpacity="0.22" />
          <stop offset="1" stopColor="#7ED3C8" stopOpacity="0" />
        </linearGradient>
        <linearGradient id="weaveAmberSoft" x1="-100" x2="1100" y1="0" y2="0" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#F3D48B" stopOpacity="0" />
          <stop offset="0.55" stopColor="#D5A44A" stopOpacity="0.18" />
          <stop offset="1" stopColor="#F3D48B" stopOpacity="0" />
        </linearGradient>
        <linearGradient id="weaveInk" x1="-100" x2="1100" y1="0" y2="0" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#0B3F39" stopOpacity="0" />
          <stop offset="0.5" stopColor="#0B3F39" stopOpacity="0.12" />
          <stop offset="1" stopColor="#0B3F39" stopOpacity="0" />
        </linearGradient>
        <radialGradient id="weaveGestureGlow" cx="50%" cy="50%" r="50%">
          <stop offset="0" stopColor="#FEF5DF" stopOpacity="0.62" />
          <stop offset="0.28" stopColor="#8BD5CB" stopOpacity="0.32" />
          <stop offset="0.62" stopColor="#D5A44A" stopOpacity="0.16" />
          <stop offset="1" stopColor="#8BD5CB" stopOpacity="0" />
        </radialGradient>
        <filter id="weaveSoft" x="-16%" y="-75%" width="132%" height="250%" colorInterpolationFilters="sRGB">
          <feGaussianBlur stdDeviation="7" />
        </filter>
      </defs>

      <g ref={gestureGlowRef} opacity="0">
        <ellipse cx="0" cy="0" rx="136" ry="42" fill="url(#weaveGestureGlow)" />
      </g>
      <g>
        {weaveStrands.map((strand, index) => (
          <g key={strand.key}>
            <path
              ref={(node) => {
                glowRefs.current[index] = node;
              }}
              d={buildWeavePath(strand, initialWeavePointer, 0)}
              filter="url(#weaveSoft)"
              opacity={strand.glowOpacity}
              stroke={strand.stroke}
              strokeLinecap="round"
              strokeWidth={strand.glowWidth}
            />
            <path
              ref={(node) => {
                strandRefs.current[index] = node;
              }}
              d={buildWeavePath(strand, initialWeavePointer, 0)}
              opacity={strand.opacity}
              stroke={strand.stroke}
              strokeLinecap="round"
              strokeWidth={strand.strokeWidth}
              vectorEffect="non-scaling-stroke"
            />
          </g>
        ))}
      </g>
    </svg>
  );
}

function TechChip({ icon, name }: { icon: string; name: string }) {
  return (
    <div className="landing-copy inline-flex h-[58px] w-full min-w-0 items-center justify-center gap-2 rounded-md border border-[#e3d3bd] bg-white/84 px-3 text-[13px] font-semibold text-ink/90 shadow-[0_14px_30px_rgba(17,17,17,0.065)] backdrop-blur sm:h-[68px] sm:gap-3.5 sm:px-5 sm:text-[15px]">
      <img className="h-[24px] w-[24px] shrink-0 object-contain sm:h-[26px] sm:w-[26px]" src={icon} alt="" aria-hidden="true" />
      <span className="min-w-0 truncate">{name}</span>
    </div>
  );
}

export function LoginPage() {
  const navigate = useNavigate();
  const token = useAuthStore((state) => state.token);
  const setSession = useAuthStore((state) => state.setSession);

  const loginMutation = useMutation({
    mutationFn: api.createDemoSession,
    onSuccess: (data) => {
      setSession({ token: data.access_token, user: data.user });
      navigate("/", { replace: true });
    },
  });

  if (token) {
    return <Navigate to="/" replace />;
  }

  function enterWorkspace() {
    loginMutation.mutate();
  }

  return (
    <main className="min-h-screen overflow-hidden bg-[#fbfaf7] text-ink">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-[720px] bg-[radial-gradient(circle_at_72%_10%,rgba(25,121,109,0.12),transparent_28%),radial-gradient(circle_at_18%_22%,rgba(213,164,74,0.13),transparent_25%)]" />
      <div className="pointer-events-none absolute inset-0 opacity-[0.08] [background-image:linear-gradient(rgba(17,17,17,.18)_1px,transparent_1px),linear-gradient(90deg,rgba(17,17,17,.18)_1px,transparent_1px)] [background-size:56px_56px]" />

      <header className="relative z-10 bg-white/35 backdrop-blur-sm">
        <div className="mx-auto flex h-[92px] w-full max-w-[1680px] items-center justify-between px-8 lg:px-12">
          <BrandWordmark className="text-[38px]" />
          <button
            className="inline-flex h-12 min-w-[132px] items-center justify-center gap-2 rounded-md bg-[linear-gradient(135deg,#0E8779,#006A60)] px-8 text-base font-semibold text-white shadow-[0_16px_38px_rgba(6,95,84,0.22)] transition hover:-translate-y-0.5 hover:shadow-[0_20px_44px_rgba(6,95,84,0.28)] disabled:translate-y-0 disabled:opacity-70"
            type="button"
            disabled={loginMutation.isPending}
            onClick={enterWorkspace}
          >
            {loginMutation.isPending ? <Loader2 className="animate-spin" size={17} /> : null}
            {loginMutation.isPending ? "正在进入" : "进入工作台"}
          </button>
        </div>
      </header>

      <section className="relative z-10 mx-auto grid min-h-[calc(100vh-92px)] w-full min-w-0 max-w-[1680px] items-start gap-8 px-6 pb-12 pt-10 sm:px-8 lg:grid-cols-[minmax(520px,0.86fr)_minmax(0,1fr)] lg:gap-7 lg:px-12 xl:grid-cols-[minmax(620px,0.9fr)_minmax(0,1fr)] xl:gap-9 2xl:grid-cols-[minmax(700px,0.92fr)_minmax(0,1fr)] 2xl:gap-12">
        <FlowRibbon />

        <div className="relative w-full min-w-0 max-w-[720px] pt-10 md:pt-12 lg:max-w-[680px] xl:max-w-[760px] xl:pt-[72px]">
          <h1 className="landing-title inline-block text-[44px] font-medium leading-[1.08] tracking-normal text-ink sm:text-[54px] md:text-[66px] lg:text-[58px] xl:text-[72px] 2xl:text-[82px]">
            <span className="block whitespace-nowrap">
              为一线老师准备的
              <span className="absolute">，</span>
            </span>
            <span className="block text-center lg:whitespace-nowrap">一站式备课助手</span>
          </h1>

          <p className="landing-copy mt-8 max-w-2xl text-[17px] leading-8 text-ink/62 sm:text-[18px] sm:leading-9 xl:mt-9 xl:text-[20px] xl:leading-10">
            从教材解析、学情匹配到课程大纲、教案、课件和练习，
            <br />
            EduWeave 帮您把备课流程串起来。
          </p>

          <div className="mt-10 grid w-full max-w-[660px] grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 xl:mt-12" aria-label="EduWeave 技术栈">
            {techStack.map((tech) => (
              <TechChip key={tech.name} icon={tech.icon} name={tech.name} />
            ))}
          </div>

          {loginMutation.error ? <div className="mt-6 text-sm font-semibold text-coral">{loginMutation.error.message}</div> : null}
        </div>

        <ProductDemo />
      </section>
    </main>
  );
}
