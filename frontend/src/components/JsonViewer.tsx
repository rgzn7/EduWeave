function stringifyJson(value: unknown) {
  if (value === undefined || value === null || value === "") {
    return "";
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function JsonViewer({ title, value }: { title: string; value: unknown }) {
  const content = stringifyJson(value);

  return (
    <section className="rounded-md border border-line bg-paper/60">
      <div className="border-b border-line px-4 py-3 text-sm font-bold">{title}</div>
      {content ? (
        <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words p-4 text-xs leading-5 text-ink/75">{content}</pre>
      ) : (
        <div className="p-4 text-sm text-ink/45">暂无记录</div>
      )}
    </section>
  );
}
