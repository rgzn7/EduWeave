import { FormEvent, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { BookOpen, Loader2 } from "lucide-react";
import { Navigate, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useAuthStore } from "../stores/auth";

export function LoginPage() {
  const navigate = useNavigate();
  const token = useAuthStore((state) => state.token);
  const setSession = useAuthStore((state) => state.setSession);
  const [username, setUsername] = useState("teacher_demo");
  const [password, setPassword] = useState("Teacher@123");

  const loginMutation = useMutation({
    mutationFn: api.login,
    onSuccess: (data) => {
      setSession({ token: data.access_token, user: data.user });
      navigate("/", { replace: true });
    },
  });

  if (token) {
    return <Navigate to="/" replace />;
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    loginMutation.mutate({ username, password });
  }

  return (
    <main className="grid min-h-screen bg-paper text-ink lg:grid-cols-[1fr_440px]">
      <section className="relative hidden overflow-hidden bg-ink text-white lg:block">
        <div className="absolute inset-0 bg-[linear-gradient(135deg,#132022_0%,#173235_48%,#314036_100%)]" />
        <div className="absolute inset-0 opacity-20 [background-image:linear-gradient(rgba(255,255,255,.18)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,.18)_1px,transparent_1px)] [background-size:42px_42px]" />
        <div className="relative flex h-full flex-col justify-between p-12">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-md bg-accent">
              <BookOpen size={23} />
            </div>
            <div>
              <div className="text-lg font-bold">EduWeave</div>
              <div className="text-sm text-white/55">教材到课堂生成链路</div>
            </div>
          </div>
          <div className="max-w-2xl">
            <h1 className="max-w-xl text-5xl font-bold leading-tight">教师资源编排工作台</h1>
            <div className="mt-8 grid max-w-xl grid-cols-3 gap-3 text-sm text-white/72">
              <div className="rounded-lg border border-white/10 bg-white/10 p-4">
                <div className="text-2xl font-bold text-white">01</div>
                <div className="mt-2">教材解析</div>
              </div>
              <div className="rounded-lg border border-white/10 bg-white/10 p-4">
                <div className="text-2xl font-bold text-white">02</div>
                <div className="mt-2">知识结构化</div>
              </div>
              <div className="rounded-lg border border-white/10 bg-white/10 p-4">
                <div className="text-2xl font-bold text-white">03</div>
                <div className="mt-2">资源生成</div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="flex items-center justify-center px-5 py-10">
        <form className="panel w-full max-w-md p-6" onSubmit={handleSubmit}>
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <div className="flex h-10 w-10 items-center justify-center rounded-md bg-ink text-white">
              <BookOpen size={20} />
            </div>
            <div>
              <div className="font-bold">EduWeave</div>
              <div className="text-xs text-ink/55">教师工作台</div>
            </div>
          </div>
          <div>
            <h2 className="text-2xl font-bold">登录</h2>
            <p className="mt-2 text-sm text-ink/55">教师账号</p>
          </div>
          <div className="mt-7 space-y-4">
            <label className="block">
              <span className="label">用户名</span>
              <input className="field mt-2" value={username} onChange={(event) => setUsername(event.target.value)} />
            </label>
            <label className="block">
              <span className="label">密码</span>
              <input
                className="field mt-2"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </label>
          </div>
          {loginMutation.error ? <div className="mt-4 text-sm font-semibold text-coral">{loginMutation.error.message}</div> : null}
          <button className="btn btn-primary mt-6 w-full" disabled={loginMutation.isPending} type="submit">
            {loginMutation.isPending ? <Loader2 className="animate-spin" size={17} /> : null}
            进入工作台
          </button>
        </form>
      </section>
    </main>
  );
}
