import { cn } from "../utils";

type BrandWordmarkProps = {
  className?: string;
  tone?: "default" | "inverse";
};

export function BrandWordmark({ className, tone = "default" }: BrandWordmarkProps) {
  return (
    <span className={cn("inline-flex items-center", className)}>
      <img
        className="h-[1em] w-auto"
        src={tone === "inverse" ? "/assets/brand/eduweave-wordmark-light.svg" : "/assets/brand/eduweave-wordmark.svg"}
        alt="EduWeave"
      />
    </span>
  );
}
