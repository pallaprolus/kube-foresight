/**
 * kube-foresight Chart.js rendering functions.
 */

const KF_COLORS = {
    blue: '#3b82f6',
    green: '#10b981',
    amber: '#f59e0b',
    red: '#ef4444',
    purple: '#8b5cf6',
    cyan: '#06b6d4',
    pink: '#ec4899',
    indigo: '#6366f1',
    teal: '#14b8a6',
    orange: '#f97316',
};

const COLOR_PALETTE = Object.values(KF_COLORS);

/**
 * Horizontal bar chart: CPU & Memory utilization per deployment.
 */
function renderUtilizationChart(canvasId, profiles) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;

    const labels = profiles.map(p => p.name);
    const cpuData = profiles.map(p => p.cpu_utilization_pct);
    const memData = profiles.map(p => p.memory_utilization_pct);

    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'CPU Utilization %',
                    data: cpuData,
                    backgroundColor: KF_COLORS.blue + '99',
                    borderColor: KF_COLORS.blue,
                    borderWidth: 1,
                },
                {
                    label: 'Memory Utilization %',
                    data: memData,
                    backgroundColor: KF_COLORS.purple + '99',
                    borderColor: KF_COLORS.purple,
                    borderWidth: 1,
                },
            ],
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'top' },
            },
            scales: {
                x: {
                    beginAtZero: true,
                    max: 100,
                    title: { display: true, text: 'Utilization (%)' },
                },
            },
        },
    });
}

/**
 * Time-series line chart with request/limit threshold lines.
 * Optional forecastData parameter adds a dashed forecast line with confidence band.
 * forecastData shape: { forecast_points: [{timestamp, value, lower_bound, upper_bound}], trend, days_until_request_breach }
 */
function renderTimeseriesChart(canvasId, tsData, resource, title, forecastData) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;

    const resData = tsData[resource];
    const labels = tsData.labels;
    const isMemory = resource === 'memory';
    const unit = isMemory ? 'Mi' : 'cores';

    const datasets = [
        {
            label: `${title}`,
            data: resData.usage,
            borderColor: KF_COLORS.blue,
            backgroundColor: KF_COLORS.blue + '20',
            borderWidth: 1.5,
            fill: true,
            pointRadius: 0,
            tension: 0.3,
        },
    ];

    // Add forecast overlay datasets if available
    if (forecastData && forecastData.forecast_points && forecastData.forecast_points.length > 0) {
        const fcPoints = forecastData.forecast_points;
        const fcLabels = fcPoints.map(fp => fp.timestamp);
        const fcValues = fcPoints.map(fp => isMemory ? fp.value / (1024 * 1024) : fp.value);
        const fcUpper = fcPoints.map(fp => isMemory ? fp.upper_bound / (1024 * 1024) : fp.upper_bound);
        const fcLower = fcPoints.map(fp => isMemory ? fp.lower_bound / (1024 * 1024) : fp.lower_bound);

        // Forecast line (dashed orange)
        datasets.push({
            label: 'Forecast',
            data: fcLabels.map((t, i) => ({ x: t, y: fcValues[i] })),
            borderColor: KF_COLORS.orange,
            borderWidth: 2,
            borderDash: [6, 4],
            pointRadius: 0,
            fill: false,
            tension: 0.1,
        });

        // Confidence band (upper bound)
        datasets.push({
            label: 'Upper bound',
            data: fcLabels.map((t, i) => ({ x: t, y: fcUpper[i] })),
            borderColor: 'transparent',
            backgroundColor: KF_COLORS.orange + '15',
            pointRadius: 0,
            fill: '+1',
        });

        // Confidence band (lower bound)
        datasets.push({
            label: 'Lower bound',
            data: fcLabels.map((t, i) => ({ x: t, y: fcLower[i] })),
            borderColor: 'transparent',
            backgroundColor: 'transparent',
            pointRadius: 0,
            fill: false,
        });
    }

    new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: datasets,
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { intersect: false, mode: 'index' },
            plugins: {
                legend: {
                    display: !!(forecastData && forecastData.forecast_points && forecastData.forecast_points.length),
                    labels: {
                        filter: function(item) {
                            return item.text !== 'Upper bound' && item.text !== 'Lower bound';
                        },
                    },
                },
                annotation: {
                    annotations: {
                        requestLine: {
                            type: 'line',
                            yMin: resData.request,
                            yMax: resData.request,
                            borderColor: KF_COLORS.amber,
                            borderWidth: 2,
                            borderDash: [6, 4],
                            label: {
                                display: true,
                                content: `Request: ${resData.request} ${unit}`,
                                position: 'start',
                                backgroundColor: KF_COLORS.amber + 'DD',
                                font: { size: 10 },
                            },
                        },
                        limitLine: {
                            type: 'line',
                            yMin: resData.limit,
                            yMax: resData.limit,
                            borderColor: KF_COLORS.red,
                            borderWidth: 2,
                            borderDash: [6, 4],
                            label: {
                                display: true,
                                content: `Limit: ${resData.limit} ${unit}`,
                                position: 'end',
                                backgroundColor: KF_COLORS.red + 'DD',
                                font: { size: 10 },
                            },
                        },
                    },
                },
            },
            scales: {
                x: {
                    type: 'time',
                    time: { unit: 'hour', displayFormats: { hour: 'MMM d HH:mm' } },
                    ticks: { maxTicksLimit: 8, font: { size: 10 } },
                },
                y: {
                    beginAtZero: true,
                    title: { display: true, text: unit },
                },
            },
        },
    });
}

/**
 * Grouped bar chart: current vs recommended CPU/memory requests.
 */
function renderRecommendationChart(canvasId, recommendations) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;

    const labels = recommendations.map(r => r.deployment_name);
    const currentCPU = recommendations.map(r => r.current_cpu_request * 1000); // to millicores
    const recCPU = recommendations.map(r => r.recommended_cpu_request * 1000);

    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Current CPU (m)',
                    data: currentCPU,
                    backgroundColor: KF_COLORS.red + '80',
                    borderColor: KF_COLORS.red,
                    borderWidth: 1,
                },
                {
                    label: 'Recommended CPU (m)',
                    data: recCPU,
                    backgroundColor: KF_COLORS.green + '80',
                    borderColor: KF_COLORS.green,
                    borderWidth: 1,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { position: 'top' } },
            scales: {
                y: {
                    beginAtZero: true,
                    title: { display: true, text: 'CPU (millicores)' },
                },
            },
        },
    });
}

/**
 * Donut chart: cost breakdown by deployment.
 */
function renderCostDonut(canvasId, costs) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;

    const labels = costs.map(c => c.deployment_name);
    const data = costs.map(c => c.current_monthly_cost_usd);
    const colors = labels.map((_, i) => COLOR_PALETTE[i % COLOR_PALETTE.length]);

    new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{
                data: data,
                backgroundColor: colors,
                borderWidth: 2,
                borderColor: '#fff',
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'right',
                    labels: { boxWidth: 12, font: { size: 11 } },
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            return `$${context.parsed.toFixed(2)}/mo`;
                        },
                    },
                },
            },
        },
    });
}

/**
 * Horizontal bar chart: monthly savings per deployment.
 */
function renderSavingsBar(canvasId, costs) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;

    const sorted = [...costs].sort((a, b) => b.monthly_savings_usd - a.monthly_savings_usd);
    const labels = sorted.map(c => c.deployment_name);
    const data = sorted.map(c => c.monthly_savings_usd);

    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Monthly Savings ($)',
                data: data,
                backgroundColor: KF_COLORS.green + '80',
                borderColor: KF_COLORS.green,
                borderWidth: 1,
            }],
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            return `$${context.parsed.x.toFixed(2)}/mo`;
                        },
                    },
                },
            },
            scales: {
                x: {
                    beginAtZero: true,
                    title: { display: true, text: 'Monthly Savings ($)' },
                },
            },
        },
    });
}

/**
 * Doughnut chart: sizing distribution (over/right/under-provisioned).
 */
function renderSizingDonut(canvasId, counts) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;

    new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: ['Over-provisioned', 'Right-sized', 'Under-provisioned'],
            datasets: [{
                data: [counts.over || 0, counts.right || 0, counts.under || 0],
                backgroundColor: [KF_COLORS.amber + 'CC', KF_COLORS.green + 'CC', KF_COLORS.red + 'CC'],
                borderWidth: 2,
                borderColor: '#fff',
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: { boxWidth: 14, font: { size: 12 } },
                },
            },
        },
    });
}

/**
 * Grouped bar chart: cloud cost comparison across providers.
 * cloudData shape: { providers: { aws: { name, total_current, total_savings }, ... }, cheapest }
 */
function renderCloudComparisonBar(canvasId, cloudData) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;

    const keys = Object.keys(cloudData.providers);
    const labels = keys.map(k => cloudData.providers[k].name);
    const currentCosts = keys.map(k => cloudData.providers[k].total_current);
    const recommendedCosts = keys.map(k => cloudData.providers[k].total_recommended);

    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Current Monthly Cost ($)',
                    data: currentCosts,
                    backgroundColor: KF_COLORS.red + '80',
                    borderColor: KF_COLORS.red,
                    borderWidth: 1,
                },
                {
                    label: 'Optimized Monthly Cost ($)',
                    data: recommendedCosts,
                    backgroundColor: KF_COLORS.green + '80',
                    borderColor: KF_COLORS.green,
                    borderWidth: 1,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'top' },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            return `${context.dataset.label}: $${context.parsed.y.toFixed(2)}/mo`;
                        },
                    },
                },
            },
            scales: {
                y: {
                    beginAtZero: true,
                    title: { display: true, text: 'Monthly Cost ($)' },
                },
            },
        },
    });
}
