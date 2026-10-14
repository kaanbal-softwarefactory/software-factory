<?php

namespace App\Http\Controllers;

use App\ViewModels\HomeViewModel;
use Inertia\Inertia;
use Inertia\Response;

class HomeController extends Controller
{
    public function __invoke(HomeViewModel $viewModel): Response
    {
        return Inertia::render('home', [
            'viewModel' => $viewModel->toArray(),
        ]);
    }
}
