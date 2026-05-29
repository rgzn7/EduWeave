/**
 * @Date: 2026-05-29
 * @Author: xisy
 * @Discription: Mermaid 单例懒加载器，首次使用时动态 import 并初始化主题/安全配置（对齐 thesis-viva）
 */
import type mermaidNamespace from "mermaid";

type MermaidModule = typeof mermaidNamespace;

let mermaidPromise: Promise<MermaidModule> | null = null;

/** 单例返回初始化后的 mermaid，避免在多处消息渲染时重复初始化。 */
export function loadMermaid(): Promise<MermaidModule> {
  if (!mermaidPromise) {
    mermaidPromise = import("mermaid").then((mod) => {
      const mermaid = mod.default;
      mermaid.initialize({
        startOnLoad: false,
        theme: "default",
        // strict 会拒绝外部资源/脚本，符合 Agent 回复在受信前端内渲染的场景
        securityLevel: "strict",
        fontFamily: "inherit",
      });
      return mermaid;
    });
  }
  return mermaidPromise;
}
