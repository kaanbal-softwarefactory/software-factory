import { Head } from '@inertiajs/react';
import { useHomeViewModel, type HomeProps } from '../view-models/use-home-view-model';

export default function Home(props: HomeProps) {
    const vm = useHomeViewModel(props);

    return (
        <main className="min-h-screen bg-slate-950 px-6 py-16 text-slate-100">
            <section className="mx-auto max-w-3xl rounded-3xl border border-slate-800 bg-slate-900 p-10 shadow-2xl">
                <Head title="Inicio" />
                <p className="mb-3 text-sm font-semibold uppercase tracking-[0.3em] text-red-400">Kaanbal</p>
                <h1 className="text-4xl font-bold">{vm.headline}</h1>
                <p className="mt-4 text-slate-300">{vm.appName} está listo para desarrollar con una separación MVVM.</p>
                <div className="mt-8 flex flex-wrap gap-2">
                    {vm.stack.map((item) => (
                        <span key={item} className="rounded-full bg-slate-800 px-3 py-1 text-sm">{item}</span>
                    ))}
                </div>
                <button
                    type="button"
                    onClick={vm.checkHealth}
                    disabled={vm.loading}
                    className="mt-8 rounded-xl bg-red-500 px-5 py-3 font-semibold text-white disabled:opacity-60"
                >
                    {vm.loading ? 'Comprobando…' : 'Probar /health'}
                </button>
                {vm.health && (
                    <pre className="mt-5 overflow-auto rounded-xl bg-black/40 p-4 text-sm text-emerald-300">
                        {JSON.stringify(vm.health, null, 2)}
                    </pre>
                )}
            </section>
        </main>
    );
}
