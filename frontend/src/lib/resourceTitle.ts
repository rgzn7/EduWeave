function stripExtension(value?: string | null) {
  return String(value ?? "")
    .replace(/\.[^.]+$/u, "")
    .trim();
}

export function getResourcePackageTitle({
  planTitle,
  batchName,
  projectName,
}: {
  planTitle?: string | null;
  batchName?: string | null;
  projectName?: string | null;
}) {
  const title = stripExtension(planTitle)
    .replace(/(?:个性化)?课程(?:大纲|总纲)$/u, "备课资源")
    .replace(/(?:个性化)?(?:课程)?(?:大纲|总纲)$/u, "备课资源")
    .trim();

  if (title) {
    return title.endsWith("备课资源") ? title : `${title}备课资源`;
  }

  return stripExtension(batchName) || stripExtension(projectName) || "备课资源";
}
