<?php

namespace App\ViewModels;

class HomeViewModel
{
    /** @return array<string, mixed> */
    public function toArray(): array
    {
        return [
            'appName' => config('app.name'),
            'headline' => 'Laravel funciona en Kaanbal',
            'stack' => ['Laravel 13', 'PHP 8.4', 'React 19', 'Inertia 3'],
            'healthUrl' => route('health'),
        ];
    }
}
