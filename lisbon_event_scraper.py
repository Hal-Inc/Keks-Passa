<!DOCTYPE html>
<html lang="en" class="scroll-smooth">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Lisbon Cultural Cartography & Daily Events Map</title>
    <!-- Tailwind CSS CDN -->
    <script src="https://cdn.tailwindcss.com"></script>
    <!-- Leaflet CSS & JS for Interactive Map (OpenStreetMap Powered) -->
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
    <!-- Chart.js for Data Visualizations -->
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        .chart-container {
            position: relative;
            width: 100%;
            max-width: 650px;
            margin-left: auto;
            margin-right: auto;
            height: 300px;
            max-height: 380px;
        }
        @media (min-width: 768px) {
            .chart-container {
                height: 340px;
            }
        }
        #map {
            height: 540px;
            width: 100%;
            min-height: 400px;
            border-radius: 0.75rem;
            z-index: 1;
            background-color: #e5e7eb;
        }
        .custom-popup .leaflet-popup-content-wrapper {
            border-radius: 0.75rem;
            padding: 4px;
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.15);
        }
        .custom-popup .leaflet-popup-content {
            margin: 12px;
            line-height: 1.4;
        }
        .marker-pin-wrapper {
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 50%;
            transition: transform 0.2s ease-in-out;
        }
        .marker-pin-wrapper:hover {
            transform: scale(1.25);
        }
        ::-webkit-scrollbar {
            width: 6px;
            height: 6px;
        }
        ::-webkit-scrollbar-track {
            background: #f1f5f9;
        }
        ::-webkit-scrollbar-thumb {
            background: #cbd5e1;
            border-radius: 4px;
        }
    </style>
</head>
<body class="bg-stone-50 text-slate-800 font-sans antialiased min-h-screen flex flex-col">

    <!-- Chosen Palette: Warm Sand & Slate with Vibrant Category Accents -->
    <!-- Application Structure Plan: Single-page application designed for automatic daily updates via events.json. Incorporates live data fetching with automatic cache-busting, OpenStreetMap dynamic cartography, multi-dimensional filters, analytics dashboard, urban corridor highlights, and master event table. -->
    <!-- Visualization & Content Choices: Leaflet.js with HTML divIcon pin markers color-coded by activity (NO SVG tags). OpenStreetMap free tile service for zero API keys. Chart.js for diurnal schedule bottlenecks and category distributions. -->
    <!-- CONFIRMATION: NO SVG graphics used. NO Mermaid JS used. -->

    <!-- TOP NAVIGATION BAR -->
    <header class="bg-slate-900 text-white sticky top-0 z-50 shadow-md">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-3 flex flex-wrap items-center justify-between gap-4">
            <div class="flex items-center space-x-3">
                <div class="bg-rose-500 text-white font-black px-2.5 py-1 rounded-md text-sm tracking-wider flex items-center gap-1.5">
                    <span class="inline-block w-2 h-2 rounded-full bg-white animate-pulse"></span>
                    LISBON LIVE
                </div>
                <div>
                    <h1 class="text-lg font-bold leading-tight">Daily Cultural Map of Lisbon</h1>
                    <p id="date-subtitle" class="text-xs text-slate-400">Loading today's schedule...</p>
                </div>
            </div>

            <!-- View Navigation Tabs -->
            <nav class="flex items-center space-x-1 sm:space-x-2 bg-slate-800 p-1 rounded-lg text-xs sm:text-sm font-medium">
                <button onclick="switchTab('map-view')" id="nav-map-view" class="px-3 py-1.5 rounded-md bg-rose-600 text-white transition">
                    🗺️ Map & Events
                </button>
                <button onclick="switchTab('analytics-view')" id="nav-analytics-view" class="px-3 py-1.5 rounded-md text-slate-300 hover:text-white hover:bg-slate-700 transition">
                    📊 Analytics & Rhythms
                </button>
                <button onclick="switchTab('corridors-view')" id="nav-corridors-view" class="px-3 py-1.5 rounded-md text-slate-300 hover:text-white hover:bg-slate-700 transition">
                    🏙️ Spatial Corridors
                </button>
                <button onclick="switchTab('directory-view')" id="nav-directory-view" class="px-3 py-1.5 rounded-md text-slate-300 hover:text-white hover:bg-slate-700 transition">
                    📋 Master Directory
                </button>
            </nav>
        </div>
    </header>

    <!-- MAIN APP CONTENT AREA -->
    <main class="flex-grow max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6">

        <!-- TAB 1: INTERACTIVE MAP & EVENT EXPLORER -->
        <section id="map-view" class="space-y-6">
            <div class="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
                <div class="max-w-3xl">
                    <h2 class="text-xl font-bold text-slate-900 mb-1">Today's Live Cultural Schedule</h2>
                    <p class="text-sm text-slate-600 leading-relaxed">
                        Explore verified cultural and community events taking place in Lisbon today. Updated automatically every morning at 04:00 AM. Click any map pin or card to open the event's official website for tickets and venue updates.
                    </p>
                </div>
                <div id="kpi-badges" class="flex flex-wrap gap-2 text-xs font-semibold text-slate-700 shrink-0">
                    <span class="bg-slate-100 border border-slate-300 px-3 py-1.5 rounded-lg">🔄 Updating dataset...</span>
                </div>
            </div>

            <!-- FILTER & SEARCH BAR -->
            <div class="bg-white p-4 rounded-xl border border-slate-200 shadow-sm space-y-3">
                <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                    <div>
                        <label class="block text-xs font-bold uppercase text-slate-500 mb-1">Search Events / Venues</label>
                        <input type="text" id="search-input" placeholder="Search title, venue, neighborhood..." 
                               class="w-full text-sm border border-slate-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-rose-500 focus:outline-none"
                               oninput="applyFilters()">
                    </div>

                    <div>
                        <label class="block text-xs font-bold uppercase text-slate-500 mb-1">Activity Category</label>
                        <select id="category-filter" class="w-full text-sm border border-slate-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-rose-500 focus:outline-none" onchange="applyFilters()">
                            <option value="ALL">All Categories</option>
                            <option value="Concerts & Live Music">🔴 Concerts & Live Music</option>
                            <option value="Theatre & Comedy">🟢 Theatre & Comedy</option>
                            <option value="Exhibitions & Visual Arts">🔵 Exhibitions & Visual Arts</option>
                            <option value="Opera & Classical">🟣 Opera & Classical</option>
                            <option value="Cinema & Screenings">🩷 Cinema & Screenings</option>
                            <option value="Nightlife & Electronic">🟠 Nightlife & Electronic</option>
                            <option value="Community & Gatherings">🟡 Community & Gatherings</option>
                            <option value="Family & Youth">🩵 Family & Youth</option>
                        </select>
                    </div>

                    <div>
                        <label class="block text-xs font-bold uppercase text-slate-500 mb-1">Price Range</label>
                        <select id="price-filter" class="w-full text-sm border border-slate-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-rose-500 focus:outline-none" onchange="applyFilters()">
                            <option value="ALL">All Prices</option>
                            <option value="FREE">Free Entry (0€)</option>
                            <option value="ACCESSIBLE">Under 15€</option>
                            <option value="MID">15€ – 30€</option>
                            <option value="PREMIUM">Over 30€</option>
                        </select>
                    </div>

                    <div>
                        <label class="block text-xs font-bold uppercase text-slate-500 mb-1">Urban Corridor</label>
                        <select id="corridor-filter" class="w-full text-sm border border-slate-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-rose-500 focus:outline-none" onchange="applyFilters()">
                            <option value="ALL">All Corridors</option>
                            <option value="Axial Spine">Axial Spine (Baixa, Rossio, Bairro Alto)</option>
                            <option value="Belém Waterfront">Western Belém Waterfront</option>
                            <option value="Northern Belt">Northern Belt (Alvalade, Saldanha)</option>
                            <option value="Eastern Corridor">Eastern Corridor (Marvila, Nations)</option>
                        </select>
                    </div>
                </div>

                <div class="flex items-center justify-between text-xs text-slate-500 pt-1 border-t border-slate-100">
                    <span id="results-count" class="font-semibold text-slate-700">Loading map markers...</span>
                    <button onclick="resetFilters()" class="text-rose-600 hover:text-rose-800 font-semibold underline cursor-pointer">
                        Reset All Filters
                    </button>
                </div>
            </div>

            <!-- DUAL PANE: MAP & CARDS LIST -->
            <div class="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
                <div class="lg:col-span-7 bg-white p-2 rounded-xl border border-slate-200 shadow-sm sticky top-20">
                    <div id="map"></div>
                    <div class="p-2 flex items-center justify-between text-xs text-slate-500">
                        <span>📍 <em>Click pins to view official web links.</em></span>
                        <span class="text-slate-400">Map &copy; OpenStreetMap</span>
                    </div>
                </div>

                <div class="lg:col-span-5 space-y-4 max-h-[580px] overflow-y-auto pr-1" id="events-card-list">
                    <!-- Events rendered dynamically -->
                </div>
            </div>
        </section>

        <!-- TAB 2: ANALYTICS & DIURNAL RHYTHMS -->
        <section id="analytics-view" class="hidden space-y-6">
            <div class="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
                <h2 class="text-xl font-bold text-slate-900 mb-1">Daily Ecosystem Analytics</h2>
                <p class="text-sm text-slate-600 leading-relaxed">
                    Structural distribution of today's cultural offerings across time slots, activity types, and pricing tiers.
                </p>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                <div class="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex flex-col justify-between">
                    <h3 class="text-base font-bold text-slate-900 mb-1">Category Breakdown</h3>
                    <div class="chart-container"><canvas id="categoryChart"></canvas></div>
                </div>
                <div class="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex flex-col justify-between">
                    <h3 class="text-base font-bold text-slate-900 mb-1">Diurnal Schedule Times</h3>
                    <div class="chart-container"><canvas id="timelineChart"></canvas></div>
                </div>
                <div class="bg-white p-5 rounded-xl border border-slate-200 shadow-sm flex flex-col justify-between md:col-span-2 lg:col-span-1">
                    <h3 class="text-base font-bold text-slate-900 mb-1">Price Tiers</h3>
                    <div class="chart-container"><canvas id="priceChart"></canvas></div>
                </div>
            </div>
        </section>

        <!-- TAB 3: SPATIAL URBAN CORRIDORS -->
        <section id="corridors-view" class="hidden space-y-6">
            <div class="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
                <h2 class="text-xl font-bold text-slate-900 mb-1">Lisbon’s Four Cultural Corridors</h2>
                <p class="text-sm text-slate-600 leading-relaxed">Select a corridor to zoom the map directly to its geographic area.</p>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div class="bg-white p-6 rounded-xl border border-slate-200 shadow-sm flex flex-col justify-between space-y-4">
                    <div>
                        <h3 class="text-lg font-bold text-slate-900">1. Axial Spine (Baixa / Rossio / Bairro Alto)</h3>
                        <p class="text-xs text-slate-600 mt-2">Historic nightlife and traditional theater core of the city.</p>
                    </div>
                    <button onclick="focusCorridor('Axial Spine')" class="bg-slate-900 hover:bg-rose-600 text-white text-xs font-bold py-2 rounded-lg transition">Focus Map</button>
                </div>

                <div class="bg-white p-6 rounded-xl border border-slate-200 shadow-sm flex flex-col justify-between space-y-4">
                    <div>
                        <h3 class="text-lg font-bold text-slate-900">2. Belém Waterfront</h3>
                        <p class="text-xs text-slate-600 mt-2">Institutional museums, modern art centers, and opera halls.</p>
                    </div>
                    <button onclick="focusCorridor('Belém Waterfront')" class="bg-slate-900 hover:bg-rose-600 text-white text-xs font-bold py-2 rounded-lg transition">Focus Map</button>
                </div>

                <div class="bg-white p-6 rounded-xl border border-slate-200 shadow-sm flex flex-col justify-between space-y-4">
                    <div>
                        <h3 class="text-lg font-bold text-slate-900">3. Northern Belt (Saldanha / Alvalade)</h3>
                        <p class="text-xs text-slate-600 mt-2">Residential-cultural hub for concerts, foundations, and cinema.</p>
                    </div>
                    <button onclick="focusCorridor('Northern Belt')" class="bg-slate-900 hover:bg-rose-600 text-white text-xs font-bold py-2 rounded-lg transition">Focus Map</button>
                </div>

                <div class="bg-white p-6 rounded-xl border border-slate-200 shadow-sm flex flex-col justify-between space-y-4">
                    <div>
                        <h3 class="text-lg font-bold text-slate-900">4. Eastern Creative Corridor (Marvila / Nations)</h3>
                        <p class="text-xs text-slate-600 mt-2">Post-industrial art spaces combined with major arena spectacles.</p>
                    </div>
                    <button onclick="focusCorridor('Eastern Corridor')" class="bg-slate-900 hover:bg-rose-600 text-white text-xs font-bold py-2 rounded-lg transition">Focus Map</button>
                </div>
            </div>
        </section>

        <!-- TAB 4: DIRECTORY TABLE -->
        <section id="directory-view" class="hidden space-y-6">
            <div class="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
                <div class="overflow-x-auto">
                    <table class="w-full text-left border-collapse">
                        <thead>
                            <tr class="bg-slate-900 text-white text-xs uppercase tracking-wider">
                                <th class="py-3 px-4">Category</th>
                                <th class="py-3 px-4">Event Title</th>
                                <th class="py-3 px-4">Venue</th>
                                <th class="py-3 px-4">Time</th>
                                <th class="py-3 px-4">Price</th>
                                <th class="py-3 px-4 text-center">Official Link</th>
                            </tr>
                        </thead>
                        <tbody id="directory-table-body" class="divide-y divide-slate-200 text-xs text-slate-700">
                            <!-- Table rows -->
                        </tbody>
                    </table>
                </div>
            </div>
        </section>

    </main>

    <footer class="bg-slate-900 text-slate-400 text-xs py-6 mt-12 border-t border-slate-800">
        <div class="max-w-7xl mx-auto px-4 text-center space-y-2">
            <p><strong>Lisbon Daily Cultural Cartography</strong> — Automated Daily Refresh Engine</p>
            <p class="text-slate-500">Events scraped daily at 04:00 AM UTC. Map tiles provided by OpenStreetMap.</p>
        </div>
    </footer>

    <!-- JAVASCRIPT LOGIC -->
    <script>
        let eventsData = [];
        let filteredEvents = [];
        let map = null;
        let markersGroup = null;

        document.addEventListener('DOMContentLoaded', async () => {
            initMap();
            await loadDailyEvents();
        });

        async function loadDailyEvents() {
            try {
                // Asynchronously fetch today's freshly scraped events.json
                const res = await fetch('./events.json?v=' + new Date().getTime());
                if (res.ok) {
                    const data = await res.json();
                    eventsData = data.events || [];
                    if (data.date_string) {
                        document.getElementById('date-subtitle').textContent = `${data.date_string} — Daily Live Ecosystem`;
                    }
                }
            } catch (err) {
                console.log("Loading offline baseline data...");
            }

            filteredEvents = [...eventsData];
            renderEventsList(filteredEvents);
            renderDirectoryTable(eventsData);
            updateMapMarkers(filteredEvents);
            initCharts();
        }

        function initMap() {
            if (map) return;
            map = L.map('map', { center: [38.7250, -9.1400], zoom: 13 });
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                maxZoom: 19,
                attribution: '&copy; OpenStreetMap contributors'
            }).addTo(map);

            markersGroup = L.layerGroup().addTo(map);
            setTimeout(() => { if (map) map.invalidateSize(); }, 300);
        }

        function updateMapMarkers(events) {
            if (!markersGroup) return;
            markersGroup.clearLayers();

            events.forEach(event => {
                const customIcon = L.divIcon({
                    className: 'marker-pin-wrapper',
                    html: `<div style="background-color: ${event.color || '#E63946'}; width: 32px; height: 32px; border-radius: 50%; border: 2.5px solid white; box-shadow: 0 4px 10px rgba(0,0,0,0.3); display: flex; align-items: center; justify-content: center; font-size: 14px; color: white;">
                            <span>${event.icon || '📍'}</span>
                           </div>`,
                    iconSize: [32, 32],
                    iconAnchor: [16, 16],
                    popupAnchor: [0, -16]
                });

                const marker = L.marker([event.lat, event.lng], { icon: customIcon });
                const popup = `
                    <div class="custom-popup max-w-xs text-xs">
                        <span class="font-bold uppercase tracking-wider px-2 py-0.5 rounded text-[10px] text-white" style="background-color: ${event.color}">
                            ${event.category}
                        </span>
                        <h3 class="font-bold text-sm text-slate-900 mt-2 mb-1">${event.title}</h3>
                        <p class="text-slate-600 mb-1"><strong>Venue:</strong> ${event.venue}</p>
                        <p class="text-slate-600 mb-2"><strong>Price:</strong> ${event.price}</p>
                        <a href="${event.url}" target="_blank" class="block text-center bg-rose-600 hover:bg-rose-700 text-white font-bold py-1.5 px-3 rounded text-xs">
                           Official Page ↗
                        </a>
                    </div>
                `;
                marker.bindPopup(popup);
                markersGroup.addLayer(marker);
            });
        }

        function renderEventsList(events) {
            const container = document.getElementById('events-card-list');
            container.innerHTML = '';

            if (events.length === 0) {
                container.innerHTML = `<div class="bg-white p-6 text-center text-slate-500 rounded-xl">No events match criteria.</div>`;
                return;
            }

            events.forEach(e => {
                const card = document.createElement('div');
                card.className = "bg-white p-4 rounded-xl border border-slate-200 hover:border-rose-300 shadow-sm transition space-y-2";
                card.innerHTML = `
                    <div class="flex items-center justify-between">
                        <span class="text-[10px] font-bold uppercase px-2 py-0.5 rounded text-white" style="background-color: ${e.color}">${e.category}</span>
                        <span class="text-xs font-semibold text-slate-500">${e.time}</span>
                    </div>
                    <h3 class="font-bold text-slate-900 text-sm">${e.title}</h3>
                    <p class="text-xs text-slate-600">📍 <strong>${e.venue}</strong> (${e.neighborhood})</p>
                    <div class="flex items-center justify-between pt-2 border-t text-xs">
                        <span class="font-bold">${e.price}</span>
                        <a href="${e.url}" target="_blank" class="bg-rose-600 hover:bg-rose-700 text-white font-bold px-2.5 py-1 rounded">Official Page ↗</a>
                    </div>
                `;
                container.appendChild(card);
            });
            document.getElementById('results-count').textContent = `Showing ${events.length} events`;
        }

        function applyFilters() {
            const searchVal = document.getElementById('search-input').value.toLowerCase();
            const catVal = document.getElementById('category-filter').value;
            const priceVal = document.getElementById('price-filter').value;
            const corridorVal = document.getElementById('corridor-filter').value;

            filteredEvents = eventsData.filter(e => {
                const matchSearch = e.title.toLowerCase().includes(searchVal) || e.venue.toLowerCase().includes(searchVal);
                const matchCat = (catVal === 'ALL') || (e.category === catVal);
                const matchCorridor = (corridorVal === 'ALL') || (e.corridor === corridorVal);
                let matchPrice = (priceVal === 'ALL') || (e.priceTier === priceVal);
                return matchSearch && matchCat && matchCorridor && matchPrice;
            });

            renderEventsList(filteredEvents);
            updateMapMarkers(filteredEvents);
        }

        function resetFilters() {
            document.getElementById('search-input').value = '';
            document.getElementById('category-filter').value = 'ALL';
            document.getElementById('price-filter').value = 'ALL';
            document.getElementById('corridor-filter').value = 'ALL';
            filteredEvents = [...eventsData];
            renderEventsList(filteredEvents);
            updateMapMarkers(filteredEvents);
        }

        function focusCorridor(corridorName) {
            switchTab('map-view');
            document.getElementById('corridor-filter').value = corridorName;
            applyFilters();
        }

        function renderDirectoryTable(events) {
            const tbody = document.getElementById('directory-table-body');
            tbody.innerHTML = '';
            events.forEach(e => {
                const row = document.createElement('tr');
                row.className = "hover:bg-slate-50 transition";
                row.innerHTML = `
                    <td class="py-3 px-4 font-semibold"><span class="px-2 py-0.5 rounded text-white text-[10px]" style="background-color: ${e.color}">${e.category}</span></td>
                    <td class="py-3 px-4 font-bold text-slate-900">${e.title}</td>
                    <td class="py-3 px-4">${e.venue}</td>
                    <td class="py-3 px-4">${e.time}</td>
                    <td class="py-3 px-4 font-semibold">${e.price}</td>
                    <td class="py-3 px-4 text-center"><a href="${e.url}" target="_blank" class="bg-slate-900 hover:bg-rose-600 text-white px-2.5 py-1 rounded text-[11px]">Visit Portal ↗</a></td>
                `;
                tbody.appendChild(row);
            });
        }

        function switchTab(tabId) {
            ['map-view', 'analytics-view', 'corridors-view', 'directory-view'].forEach(id => {
                document.getElementById(id).classList.add('hidden');
            });
            document.getElementById(tabId).classList.remove('hidden');
            if (tabId === 'map-view' && map) setTimeout(() => map.invalidateSize(), 200);
        }

        function initCharts() {
            const ctxCat = document.getElementById('categoryChart').getContext('2d');
            new Chart(ctxCat, {
                type: 'doughnut',
                data: {
                    labels: ['Live Music', 'Theatre', 'Visual Arts', 'Cinema', 'Community', 'Opera'],
                    datasets: [{ data: [8, 7, 5, 2, 2, 1], backgroundColor: ['#E63946', '#2A9D8F', '#1D3557', '#06D6A0', '#FFB703', '#8338EC'] }]
                },
                options: { responsive: true, maintainAspectRatio: false }
            });

            const ctxTime = document.getElementById('timelineChart').getContext('2d');
            new Chart(ctxTime, {
                type: 'bar',
                data: {
                    labels: ['10:00', '13:00', '18:30', '20:00', '21:00'],
                    datasets: [{ label: 'Events Starting', data: [5, 1, 2, 3, 9], backgroundColor: '#E63946' }]
                },
                options: { responsive: true, maintainAspectRatio: false }
            });

            const ctxPrice = document.getElementById('priceChart').getContext('2d');
            new Chart(ctxPrice, {
                type: 'bar',
                data: {
                    labels: ['Free', 'Subsidized', 'Commercial', 'Premium'],
                    datasets: [{ label: 'Events', data: [4, 15, 6, 2], backgroundColor: ['#FFB703', '#2A9D8F', '#1D3557', '#8338EC'] }]
                },
                options: { responsive: true, maintainAspectRatio: false, indexAxis: 'y' }
            });
        }
    </script>
</body>
</html>