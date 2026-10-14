<?php

namespace Tests\Feature;

use Inertia\Testing\AssertableInertia as Assert;
use Tests\TestCase;

class HealthTest extends TestCase
{
    public function test_health_endpoint_confirms_the_generated_project_works(): void
    {
        $this->getJson('/health')
            ->assertOk()
            ->assertJsonPath('status', 'ok')
            ->assertJsonPath('runtime', 'php')
            ->assertJsonPath('framework', 'laravel')
            ->assertJsonPath('database.connected', true);
    }

    public function test_home_renders_the_inertia_mvvm_props(): void
    {
        $this->get('/')
            ->assertOk()
            ->assertInertia(fn (Assert $page) => $page
                ->component('home')
                ->where('viewModel.headline', 'Laravel funciona en Kaanbal')
                ->has('viewModel.stack', 4));
    }
}
