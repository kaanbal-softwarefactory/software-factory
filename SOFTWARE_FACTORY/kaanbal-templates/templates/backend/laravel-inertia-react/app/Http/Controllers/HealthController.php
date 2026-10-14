<?php

namespace App\Http\Controllers;

use Illuminate\Http\JsonResponse;
use Illuminate\Support\Facades\DB;
use Throwable;

class HealthController extends Controller
{
    public function __invoke(): JsonResponse
    {
        $databaseConfigured = filled(config('database.connections.pgsql.url'))
            || app()->environment('testing');
        $databaseConnected = null;

        if ($databaseConfigured) {
            try {
                DB::select('select 1');
                $databaseConnected = true;
            } catch (Throwable) {
                $databaseConnected = false;
            }
        }

        $healthy = $databaseConnected !== false;

        return response()->json([
            'status' => $healthy ? 'ok' : 'degraded',
            'app' => config('app.name'),
            'runtime' => 'php',
            'framework' => 'laravel',
            'database' => [
                'configured' => $databaseConfigured,
                'connected' => $databaseConnected,
            ],
        ], $healthy ? 200 : 503);
    }
}
