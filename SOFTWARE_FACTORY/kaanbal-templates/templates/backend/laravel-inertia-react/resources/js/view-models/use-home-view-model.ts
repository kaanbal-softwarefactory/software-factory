import { useState } from 'react';

export interface HomeProps {
    viewModel: {
        appName: string;
        headline: string;
        stack: string[];
        healthUrl: string;
    };
}

interface HealthPayload {
    status: string;
    app: string;
    runtime: string;
    framework: string;
    database: { configured: boolean; connected: boolean | null };
}

export function useHomeViewModel({ viewModel }: HomeProps) {
    const [health, setHealth] = useState<HealthPayload | null>(null);
    const [loading, setLoading] = useState(false);

    async function checkHealth() {
        setLoading(true);
        try {
            const response = await fetch(viewModel.healthUrl, {
                headers: { Accept: 'application/json' },
            });
            setHealth((await response.json()) as HealthPayload);
        } finally {
            setLoading(false);
        }
    }

    return { ...viewModel, health, loading, checkHealth };
}
