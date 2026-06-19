let currentFilter = 7;
let currentDateRange = null;
let charts = {};
const gitlabUrl = 'https://gitlab.com';
let groupPath = '';
let repositoryName = '';
let isLoading = false;
let allUsers = [];

function createCFDChart(cfdStats) {
  if (!cfdStats || !cfdStats.dates || cfdStats.dates.length === 0) return;
  const dates = cfdStats.dates.map(d => {
    const date = new Date(d);
    return date.toLocaleDateString('de-DE', { month: 'short', day: 'numeric' });
  });
  if (charts.cfdChart) charts.cfdChart.destroy();
  const canvas = document.getElementById('cfdChart');
  const ctx = canvas.getContext('2d');

  const gradDone = ctx.createLinearGradient(0, 0, 0, 360);
  gradDone.addColorStop(0, 'rgba(56, 178, 172, 0.40)');
  gradDone.addColorStop(0.4, 'rgba(56, 178, 172, 0.15)');
  gradDone.addColorStop(1, 'rgba(56, 178, 172, 0.01)');

  const gradProgress = ctx.createLinearGradient(0, 0, 0, 360);
  gradProgress.addColorStop(0, 'rgba(108, 99, 255, 0.40)');
  gradProgress.addColorStop(0.4, 'rgba(108, 99, 255, 0.15)');
  gradProgress.addColorStop(1, 'rgba(108, 99, 255, 0.01)');

  const gradTodo = ctx.createLinearGradient(0, 0, 0, 360);
  gradTodo.addColorStop(0, 'rgba(160, 174, 192, 0.30)');
  gradTodo.addColorStop(0.4, 'rgba(160, 174, 192, 0.10)');
  gradTodo.addColorStop(1, 'rgba(160, 174, 192, 0.01)');

  function getTotal(i) {
    return (cfdStats.done[i] || 0) + (cfdStats.in_progress[i] || 0) + (cfdStats.todo[i] || 0);
  }

  charts.cfdChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: dates,
      datasets: [
        {
          label: 'Erledigt',
          data: cfdStats.done,
          backgroundColor: gradDone,
          borderColor: '#38B2AC',
          borderWidth: 3,
          fill: true,
          tension: 0.35,
          pointRadius: 4,
          pointBackgroundColor: '#38B2AC',
          pointBorderWidth: 0,
          pointHoverRadius: 8,
          pointHoverBackgroundColor: '#38B2AC',
          pointHoverBorderColor: '#fff',
          pointHoverBorderWidth: 3,
        },
        {
          label: 'In Bearbeitung',
          data: cfdStats.in_progress,
          backgroundColor: gradProgress,
          borderColor: '#6C63FF',
          borderWidth: 3,
          fill: true,
          tension: 0.35,
          pointRadius: 4,
          pointBackgroundColor: '#6C63FF',
          pointBorderWidth: 0,
          pointHoverRadius: 8,
          pointHoverBackgroundColor: '#6C63FF',
          pointHoverBorderColor: '#fff',
          pointHoverBorderWidth: 3,
        },
        {
          label: 'Offen',
          data: cfdStats.todo,
          backgroundColor: gradTodo,
          borderColor: '#A0AEC0',
          borderWidth: 3,
          fill: true,
          tension: 0.35,
          pointRadius: 4,
          pointBackgroundColor: '#A0AEC0',
          pointBorderWidth: 0,
          pointHoverRadius: 8,
          pointHoverBackgroundColor: '#A0AEC0',
          pointHoverBorderColor: '#fff',
          pointHoverBorderWidth: 3,
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: {
        duration: 1000,
        easing: 'easeOutQuart'
      },
      interaction: {
        mode: 'index',
        intersect: false,
        axis: 'x'
      },
      plugins: {
        legend: {
          display: true,
          position: 'top',
          align: 'center',
          labels: {
            usePointStyle: true,
            padding: 20,
            color: '#3D4852',
            font: { weight: '600', size: 13 },
            boxWidth: 10,
            boxHeight: 10,
          }
        },
        tooltip: {
          mode: 'index',
          intersect: false,
          backgroundColor: 'rgba(224, 229, 236, 0.95)',
          titleColor: '#3D4852',
          bodyColor: '#6B7280',
          borderColor: 'rgba(163, 177, 198, 0.4)',
          borderWidth: 1,
          cornerRadius: 16,
          padding: 14,
          titleFont: { weight: '700', size: 13 },
          bodyFont: { weight: '500', size: 12 },
          boxPadding: 6,
          usePointStyle: true,
          callbacks: {
            title: items => items[0].label,
            label: ctx => {
              const val = ctx.parsed.y;
              const total = getTotal(ctx.dataIndex);
              const pct = total > 0 ? ((val / total) * 100).toFixed(1) : 0;
              return ` ${ctx.dataset.label}: ${val} Issues (${pct}%)`;
            },
            footer: items => {
              const total = getTotal(items[0].dataIndex);
              return ' Gesamt: ' + total + ' Issues';
            }
          }
        }
      },
      scales: {
        x: {
          grid: {
            color: 'rgba(163, 177, 198, 0.12)',
            drawBorder: false,
            drawTicks: false,
          },
          ticks: {
            color: '#8B95A5',
            maxRotation: 30,
            font: { size: 11, weight: '500' },
            padding: 6,
          },
        },
        y: {
          stacked: true,
          beginAtZero: true,
          grid: {
            color: 'rgba(163, 177, 198, 0.1)',
            drawBorder: false,
            drawTicks: false,
          },
          ticks: {
            color: '#8B95A5',
            stepSize: 1,
            font: { size: 11, weight: '500' },
            padding: 8,
            crossAlign: 'near',
          },
        }
      }
    }
  });
}

function createLabelTimelineChart(labelTimelineStats) {
  if (!labelTimelineStats || !labelTimelineStats.dates || labelTimelineStats.dates.length === 0) return;
  const dates = labelTimelineStats.dates.map(d => {
    const date = new Date(d);
    return date.toLocaleDateString('de-DE', { month: 'short', day: 'numeric' });
  });
  const labels = labelTimelineStats.labels || [];
  const datasets = [];
  const labelColors = {
    'Anforderungen': { border: 'rgba(33, 150, 243, 0.8)', background: 'rgba(33, 150, 243, 0.06)' },
    'Dokumentation': { border: 'rgba(156, 39, 176, 0.8)', background: 'rgba(156, 39, 176, 0.06)' },
    'Entwurf': { border: 'rgba(0, 188, 212, 0.8)', background: 'rgba(0, 188, 212, 0.06)' },
    'Implementation & Test': { border: 'rgba(56, 178, 172, 0.8)', background: 'rgba(56, 178, 172, 0.06)' },
    'Projektmanagement': { border: 'rgba(255, 152, 0, 0.8)', background: 'rgba(255, 152, 0, 0.06)' },
    'Requirements Engineering': { border: 'rgba(233, 30, 99, 0.8)', background: 'rgba(233, 30, 99, 0.06)' }
  };
  labels.forEach(label => {
    const data = labelTimelineStats.data[label] || [];
    const colors = labelColors[label] || { border: 'rgba(96, 125, 139, 0.7)', background: 'rgba(96, 125, 139, 0.06)' };
    datasets.push({
      label,
      data,
      borderColor: colors.border,
      backgroundColor: colors.background,
      borderWidth: 2.5,
      pointRadius: 2,
      pointBackgroundColor: colors.border.replace('0.8', '1').replace('0.7', '1'),
      tension: 0.3,
      fill: true
    });
  });
  if (charts.labelTimelineChart) charts.labelTimelineChart.destroy();
  const ctx = document.getElementById('labelTimelineChart');
  charts.labelTimelineChart = new Chart(ctx, {
    type: 'line',
    data: { labels: dates, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      scales: {
        x: {
          grid: { color: 'rgba(163, 177, 198, 0.12)', drawBorder: false, drawTicks: false },
          ticks: { color: '#8B95A5', maxRotation: 30, font: { size: 11, weight: '500' } },
          title: { display: true, text: 'Datum', color: '#3D4852', font: { weight: '600', size: 12 } }
        },
        y: {
          beginAtZero: true,
          grid: { color: 'rgba(163, 177, 198, 0.1)', drawBorder: false, drawTicks: false },
          ticks: { color: '#8B95A5', font: { size: 11, weight: '500' } },
          title: { display: true, text: 'Kumulierte Stunden', color: '#3D4852', font: { weight: '600', size: 12 } }
        }
      },
      plugins: {
        legend: {
          display: true, position: 'top',
          labels: { usePointStyle: true, padding: 20, color: '#3D4852', font: { weight: '600', size: 13 }, boxWidth: 10, boxHeight: 10 }
        },
        tooltip: {
          mode: 'index', intersect: false,
          backgroundColor: 'rgba(224, 229, 236, 0.95)',
          titleColor: '#3D4852',
          bodyColor: '#6B7280',
          borderColor: 'rgba(163, 177, 198, 0.4)',
          borderWidth: 1,
          cornerRadius: 16,
          padding: 14,
          titleFont: { weight: '700', size: 13 },
          bodyFont: { weight: '500', size: 12 },
          usePointStyle: true,
          callbacks: {
            label: ctx => ' ' + ctx.dataset.label + ': ' + ctx.parsed.y + ' h',
            footer: items => ' Gesamt: ' + items.reduce((s, i) => s + i.parsed.y, 0).toFixed(2) + ' h'
          }
        }
      },
      interaction: { mode: 'nearest', axis: 'x', intersect: false }
    }
  });
}

function createUserChart(userStats) {
  const users = Object.keys(userStats).filter(u => userStats[u] > 0);
  const hours = users.map(u => userStats[u]);
  if (charts.userChart) charts.userChart.destroy();
  const ctx = document.getElementById('userChart');
  if (users.length === 0) return;
  charts.userChart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: users,
      datasets: [{
        data: hours,
        backgroundColor: [
          'rgba(108, 99, 255, 0.7)',
          'rgba(56, 178, 172, 0.7)',
          'rgba(139, 149, 165, 0.7)',
          'rgba(255, 152, 0, 0.7)',
          'rgba(33, 150, 243, 0.7)',
          'rgba(233, 30, 99, 0.6)',
          'rgba(156, 39, 176, 0.6)',
          'rgba(0, 188, 212, 0.6)'
        ],
        borderColor: '#E0E5EC',
        borderWidth: 3,
        hoverOffset: 8
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: true,
      cutout: '65%',
      plugins: {
        legend: {
          position: 'right',
          labels: { color: '#3D4852', padding: 12, usePointStyle: true }
        },
        tooltip: {
          backgroundColor: '#E0E5EC',
          titleColor: '#3D4852',
          bodyColor: '#6B7280',
          borderColor: 'rgba(163, 177, 198, 0.5)',
          borderWidth: 1,
          cornerRadius: 12,
          padding: 12,
          callbacks: {
            label: ctx => ctx.label + ': ' + ctx.parsed + ' h'
          }
        }
      }
    }
  });
}

function createLabelChart(labelStats) {
  const labels = Object.keys(labelStats).filter(l => labelStats[l].hours > 0);
  const hours = labels.map(l => labelStats[l].hours);
  const shortLabels = labels.map(l => l.split(' ')[0]);
  const palette = [
    'rgba(108, 99, 255, 0.65)',
    'rgba(56, 178, 172, 0.65)',
    'rgba(255, 152, 0, 0.65)',
    'rgba(33, 150, 243, 0.65)',
    'rgba(156, 39, 176, 0.6)',
    'rgba(233, 30, 99, 0.6)',
    'rgba(0, 188, 212, 0.6)',
    'rgba(139, 149, 165, 0.6)'
  ];
  const backgroundColors = labels.map((_, i) => palette[i % palette.length]);
  const borderColors = backgroundColors.map(c => c.replace('0.65', '0.9').replace('0.6', '0.85'));
  if (charts.labelChart) charts.labelChart.destroy();
  const ctx = document.getElementById('labelChart');
  charts.labelChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: shortLabels,
      datasets: [{
        label: 'Stunden',
        data: hours,
        backgroundColor: backgroundColors,
        borderColor: borderColors,
        borderWidth: 1,
        borderRadius: 6
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      indexAxis: 'y',
      scales: {
        x: {
          beginAtZero: true,
          grid: { color: 'rgba(163, 177, 198, 0.2)' },
          ticks: { color: '#6B7280' },
          title: { display: true, text: 'Stunden', color: '#3D4852' }
        },
        y: {
          grid: { display: false },
          ticks: { color: '#3D4852', font: { weight: '500' } }
        }
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#E0E5EC',
          titleColor: '#3D4852',
          bodyColor: '#6B7280',
          borderColor: 'rgba(163, 177, 198, 0.5)',
          borderWidth: 1,
          cornerRadius: 12,
          padding: 12,
          callbacks: {
            title: ctx => labels[ctx[0].dataIndex],
            label: ctx => ctx.parsed.x + ' h'
          }
        }
      }
    }
  });
}

async function loadData(days = null, forceRefresh = false) {
  if (isLoading) return;
  const maxRetries = 5;
  let success = false;
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      isLoading = true;
      updateReloadButton(true);
      const loadingDiv = document.getElementById('loading');
      const progressFill = document.getElementById('progressFill');
      const progressText = document.getElementById('loadingText');
      progressFill.classList.remove('done');
      progressFill.style.width = '0%';
      progressText.textContent = attempt > 1 ? `Wiederholung ${attempt}/${maxRetries}...` : 'Daten werden geladen...';
      loadingDiv.classList.remove('hidden');
      document.getElementById('content').classList.add('hidden');
      document.getElementById('error').classList.add('hidden');
      const baseParams = [];
      if (days !== null) baseParams.push(`days=${days}`);
      let fetchUrl = "/api/data";
      const fetchParams = [...baseParams];
      if (forceRefresh) fetchParams.push('refresh=true');
      if (fetchParams.length > 0) fetchUrl += '?' + fetchParams.join('&');
      let url = "/api/data";
      if (baseParams.length > 0) url += '?' + baseParams.join('&');
      let res = await fetch(fetchUrl);
      let response = await res.json();
      if (response.loading) {
        while (true) {
          await new Promise(r => setTimeout(r, 1000));
          const pRes = await fetch('/api/progress');
          const pData = await pRes.json();
          progressFill.style.width = pData.pct + '%';
          progressText.textContent = pData.msg || 'Lade Daten...';
          if (!pData.loading) break;
        }
        res = await fetch(url);
        response = await res.json();
        progressFill.style.width = '100%';
        progressFill.classList.add('done');
        progressText.textContent = 'Fertig!';
      }
      if (!response.success) throw new Error(response.error || 'Fehler beim Laden der Daten');
      const data = response.data;
      const users = response.users || [];
      const labels = response.labels || [];
      const stats = response.stats || {};
      groupPath = response.group_path || '';
      repositoryName = response.repository_name || '';
      allUsers = users;
      loadingDiv.classList.add('hidden');
      document.getElementById('content').classList.remove('hidden');
      createStatsCards(stats);
      createTopIssuesList(data);
      createUserChart(stats.user_stats);
      createLabelChart(stats.label_stats);
      createCFDChart(stats.cfd_stats);
      createLabelTimelineChart(stats.label_timeline_stats);
      createUserLabelMatrixTable(stats.user_label_matrix);
      createLeaderboard(stats.user_stats, stats.user_issue_count);
      createTreeDiagram(data, users);
      success = true;
      return;
    } catch (error) {
      console.error(`Error loading data (attempt ${attempt}/${maxRetries}):`, error);
      if (attempt < maxRetries) {
        document.getElementById('error').classList.add('hidden');
        const progressText = document.getElementById('loadingText');
        progressText.textContent = `Fehler, Wiederholung ${attempt + 1}/${maxRetries} in 2s...`;
        await new Promise(r => setTimeout(r, 2000));
      } else {
        document.getElementById('loading').classList.add('hidden');
        const errorDiv = document.getElementById('error');
        errorDiv.innerHTML = '<strong>Fehler:</strong> ' + error.message;
        errorDiv.classList.remove('hidden');
      }
    } finally {
      if (success || attempt === maxRetries) {
        isLoading = false;
        updateReloadButton(false);
      }
    }
  }
}

async function loadDataWithDateRange(startDate, endDate, forceRefresh = false) {
  if (isLoading) return;
  const maxRetries = 3;
  let success = false;
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      isLoading = true;
      updateReloadButton(true);
      const loadingDiv = document.getElementById('loading');
      const progressFill = document.getElementById('progressFill');
      const progressText = document.getElementById('loadingText');
      progressFill.classList.remove('done');
      progressFill.style.width = '0%';
      progressText.textContent = attempt > 1 ? `Wiederholung ${attempt}/${maxRetries}...` : 'Daten werden geladen...';
      loadingDiv.classList.remove('hidden');
      document.getElementById('content').classList.add('hidden');
      document.getElementById('error').classList.add('hidden');
      const baseParams = [
        `start_date=${encodeURIComponent(startDate)}`,
        `end_date=${encodeURIComponent(endDate)}`
      ];
      let fetchUrl = "/api/data";
      const fetchParams = [...baseParams];
      if (forceRefresh) fetchParams.push('refresh=true');
      fetchUrl += '?' + fetchParams.join('&');
      let url = "/api/data?" + baseParams.join('&');
      let res = await fetch(fetchUrl);
      let response = await res.json();
      if (response.loading) {
        while (true) {
          await new Promise(r => setTimeout(r, 1000));
          const pRes = await fetch('/api/progress');
          const pData = await pRes.json();
          progressFill.style.width = pData.pct + '%';
          progressText.textContent = pData.msg || 'Lade Daten...';
          if (!pData.loading) break;
        }
        res = await fetch(url);
        response = await res.json();
        progressFill.style.width = '100%';
        progressFill.classList.add('done');
        progressText.textContent = 'Fertig!';
      }
      if (!response.success) throw new Error(response.error || 'Fehler beim Laden der Daten');
      const data = response.data;
      const users = response.users || [];
      const labels = response.labels || [];
      const stats = response.stats || {};
      groupPath = response.group_path || '';
      repositoryName = response.repository_name || '';
      allUsers = users;
      loadingDiv.classList.add('hidden');
      document.getElementById('content').classList.remove('hidden');
      createStatsCards(stats);
      createTopIssuesList(data);
      createUserChart(stats.user_stats);
      createLabelChart(stats.label_stats);
      createCFDChart(stats.cfd_stats);
      createLabelTimelineChart(stats.label_timeline_stats);
      createUserLabelMatrixTable(stats.user_label_matrix);
      createLeaderboard(stats.user_stats, stats.user_issue_count);
      createTreeDiagram(data, users);
      success = true;
      return;
    } catch (error) {
      console.error(`Error loading data (attempt ${attempt}/${maxRetries}):`, error);
      if (attempt < maxRetries) {
        document.getElementById('error').classList.add('hidden');
        const progressText = document.getElementById('loadingText');
        progressText.textContent = `Fehler, Wiederholung ${attempt + 1}/${maxRetries} in 2s...`;
        await new Promise(r => setTimeout(r, 2000));
      } else {
        document.getElementById('loading').classList.add('hidden');
        const errorDiv = document.getElementById('error');
        errorDiv.innerHTML = '<strong>Fehler:</strong> ' + error.message;
        errorDiv.classList.remove('hidden');
      }
    } finally {
      if (success || attempt === maxRetries) {
        isLoading = false;
        updateReloadButton(false);
      }
    }
  }
}

function reloadData() {
  if (isLoading) return;
  if (currentDateRange) {
    loadDataWithDateRange(currentDateRange.start, currentDateRange.end, true);
  } else {
    loadData(currentFilter, true);
  }
}

function filterByDays(days, el) {
  currentFilter = days;
  currentDateRange = null;
  document.querySelectorAll('.neu-period-btn').forEach(btn => {
    btn.classList.remove('active');
  });
  if (el) el.classList.add('active');
  loadData(days, false);
}

function filterByDateRange() {
  const start = document.getElementById('startDate').value;
  const end = document.getElementById('endDate').value;
  if (!start || !end) {
    document.getElementById('error').innerHTML = '<strong>Fehler:</strong> Bitte Start- und Enddatum auswählen';
    document.getElementById('error').classList.remove('hidden');
    return;
  }
  currentDateRange = { start, end };
  currentFilter = null;
  document.querySelectorAll('.neu-period-btn').forEach(btn => btn.classList.remove('active'));
  loadDataWithDateRange(start, end, false);
}

function updateReloadButton(loading) {
  const btn = document.getElementById('reloadBtn');
  const icon = btn.querySelector('.fa-arrows-rotate');
  if (loading) {
    btn.disabled = true;
    if (icon) icon.classList.add('animate-spin-slow');
  } else {
    btn.disabled = false;
    if (icon) icon.classList.remove('animate-spin-slow');
  }
}

function createStatsCards(stats) {
  const grid = document.getElementById('statsGrid');
  let progressCard = '';
  if (currentFilter === null && currentDateRange === null) {
    progressCard = `
      <div class="neu-card p-8 text-center">
        <p class="neu-chip mb-3 inline-flex">Fortschritt</p>
        <div class="neu-stat-value text-4xl text-[#6C63FF] mt-2">${stats.total_estimated > 0 ? Math.round((stats.total_spent / stats.total_estimated) * 100) : 0}%</div>
      </div>`;
  } else {
    const createdCount = stats.creation_stats
      ? Object.values(stats.creation_stats.user_data).reduce((sum, counts) => sum + counts.reduce((a, b) => a + b, 0), 0)
      : 0;
    progressCard = `
      <div class="neu-card p-8 text-center">
        <p class="neu-chip mb-3 inline-flex">Erstellte Issues</p>
        <div class="neu-stat-value text-4xl text-[#6C63FF] mt-2">${createdCount}</div>
      </div>`;
  }
  grid.innerHTML = `
    <div class="neu-card p-8 text-center">
      <p class="neu-chip mb-3 inline-flex">Gesamte aufgewendete Zeit</p>
      <div class="neu-stat-value text-4xl text-[#3D4852] mt-2">${stats.total_spent} h</div>
    </div>
    <div class="neu-card p-8 text-center">
      <p class="neu-chip mb-3 inline-flex">Gesamte geschätzte Zeit</p>
      <div class="neu-stat-value text-4xl text-[#3D4852] mt-2">${stats.total_estimated} h</div>
    </div>
    ${progressCard}
  `;
}

function createTopIssuesList(data) {
  const issues = data.filter(d => d.Typ === 'issue' && d['Zeitaufwand (h)'] > 0);
  issues.sort((a, b) => b['Zeitaufwand (h)'] - a['Zeitaufwand (h)']);
  const topIssues = issues.slice(0, 10);
  const list = document.getElementById('topIssuesList');
  list.innerHTML = '';
  topIssues.forEach((issue, index) => {
    const li = document.createElement('li');
    const isDone = issue.state === 'closed';
    li.className = 'neu-card-inset p-4 mb-3 flex flex-col gap-2';
    if (isDone) li.style.opacity = '0.5';
    const issueUrl = `${gitlabUrl}/${groupPath}${repositoryName ? '/' + repositoryName : ''}/-/issues/${issue.IID}`;
    const workingUsers = [];
    for (const key in issue) {
      if (!['Typ', 'Titel', 'IID', 'Parent IID', 'Zeitaufwand (h)', 'gesch. Zeitaufwand (h)', 'createdAt', 'state'].includes(key)
          && typeof issue[key] === 'number' && issue[key] > 0) {
        workingUsers.push({ name: key, percentage: issue[key] });
      }
    }
    workingUsers.sort((a, b) => b.percentage - a.percentage);
    const userBadgesHtml = workingUsers.length > 0
      ? `<div class="flex gap-1.5 flex-wrap">${workingUsers.map(u => `<span class="neu-tag">${u.name.replace(/ .*/, '')} (${(u.percentage * 100).toFixed(0)}%)</span>`).join('')}</div>`
      : '';
    const titleClass = isDone ? 'font-display font-bold text-base text-[#6B7280] line-through' : 'font-display font-bold text-base';
    li.innerHTML = `
      <div class="${titleClass}">${index + 1}. <a href="${issueUrl}" target="_blank" class="text-[#6C63FF] no-underline hover:underline">#${issue.IID} ${issue.Titel}</a></div>
      <div class="flex gap-4 text-sm text-[#6B7280] flex-wrap items-center">
        <span class="font-semibold text-[#3D4852]"><i class="fa-regular fa-clock"></i> ${issue['Zeitaufwand (h)']} h verbraucht</span>
        <span class="font-medium"><i class="fa-regular fa-chart-bar"></i> ${issue['gesch. Zeitaufwand (h)']} h geschätzt</span>
        <span class="text-[#8B95A5] text-xs">ID: ${issue.IID}</span>
      </div>
      ${userBadgesHtml}`;
    list.appendChild(li);
  });
}

function createTreeDiagram(data, users) {
  const container = document.getElementById('treeContainer');
  const root = data.find(d => d.Typ === 'epic' && d['Parent IID'] === null);
  if (!root) {
    container.innerHTML = '<p class="text-[#6B7280] text-center py-8">Keine Root-Epic gefunden</p>';
    return;
  }
  const topLevelEpics = data.filter(d => d.Typ === 'epic' && d['Parent IID'] === root.IID);
  const allEpics = data.filter(d => d.Typ === 'epic' && d.IID !== root.IID);
  const issues = data.filter(d => d.Typ === 'issue');

  function getChildEpics(parentIid) { return allEpics.filter(e => e['Parent IID'] === parentIid); }
  function getDirectIssues(epicIid) { return issues.filter(i => i['Parent IID'] === epicIid); }
  function getAllIssuesForEpic(epicIid) {
    const directIssues = getDirectIssues(epicIid);
    const childEpics = getChildEpics(epicIid);
    const childIssues = childEpics.flatMap(childEpic => getAllIssuesForEpic(childEpic.IID));
    return [...directIssues, ...childIssues];
  }
  function countChildEpics(epicIid) {
    const directChildren = getChildEpics(epicIid);
    let count = directChildren.length;
    directChildren.forEach(child => { count += countChildEpics(child.IID); });
    return count;
  }

  function renderIssue(issue) {
    const issueUrl = `${gitlabUrl}/${groupPath}${repositoryName ? '/' + repositoryName : ''}/-/issues/${issue.IID}`;
    const createdDate = issue.createdAt ? new Date(issue.createdAt).toLocaleDateString('de-DE') : 'N/A';
    const isDone = issue.state === 'closed';
    const contributors = [];
    allUsers.forEach(user => {
      const percentage = issue[user];
      if (percentage > 0) contributors.push({ name: user, percentage });
    });
    contributors.sort((a, b) => b.percentage - a.percentage);
    const itemClass = isDone
      ? 'neu-card-inset p-4 flex flex-col gap-2'
      : 'neu-card-inset p-4 flex flex-col gap-2';
    const titleClass = isDone
      ? 'font-display font-bold text-[#6B7280] cursor-pointer line-through'
      : 'font-display font-bold text-[#6C63FF] cursor-pointer hover:underline';
    return `<div class="${itemClass}" style="${isDone ? 'opacity:0.5' : ''}">
      <div class="${titleClass}" onclick="window.open('${issueUrl}', '_blank')">#${issue.IID} ${issue.Titel}</div>
      <div class="flex gap-4 text-xs text-[#6B7280] flex-wrap">
        <span><i class="fa-regular fa-calendar"></i> ${createdDate}</span>
        <span class="font-semibold text-[#3D4852]"><i class="fa-regular fa-clock"></i> ${issue['Zeitaufwand (h)']} h</span>
        <span><i class="fa-regular fa-chart-bar"></i> ${issue['gesch. Zeitaufwand (h)']} h</span>
        ${isDone ? '<span class="font-semibold text-[#38B2AC]"><i class="fa-solid fa-check"></i> Closed</span>' : ''}
      </div>
      ${contributors.length > 0 ? `<div class="flex gap-1.5 flex-wrap">${contributors.map(c => `<span class="neu-tag">${c.name.split(' ')[0]} (${(c.percentage * 100).toFixed(0)}%)</span>`).join('')}</div>` : ''}
    </div>`;
  }

  function renderChildEpics(parentIid, level = 1) {
    const childEpics = getChildEpics(parentIid);
    if (childEpics.length === 0) return '';
    let html = `<div class="flex flex-col gap-3 ml-4 pl-4" style="border-left:2px solid rgba(163,177,198,0.4)">`;
    childEpics.forEach(childEpic => {
      const directIssues = getDirectIssues(childEpic.IID);
      const subChildEpics = getChildEpics(childEpic.IID);
      const totalIssues = getAllIssuesForEpic(childEpic.IID);
      const childEpicCount = countChildEpics(childEpic.IID);
      html += `<div class="flex flex-col">
        <div class="neu-card-inset p-4 cursor-pointer tree-node-content" onclick="toggleEpic(${childEpic.IID})">
          <div class="font-display font-semibold text-[#3D4852]"><i class="fa-regular fa-folder-open text-[#6C63FF]"></i> ${childEpic.Titel}</div>
          <div class="text-xs text-[#6B7280] mt-1">
            ${childEpicCount > 0 ? `${childEpicCount} Child-Epic${childEpicCount > 1 ? 's' : ''} | ` : ''}
            ${totalIssues.length} Issue${totalIssues.length !== 1 ? 's' : ''}
          </div>
          <div class="text-xs font-medium text-[#3D4852]">${childEpic['Zeitaufwand (h)']} h / ${childEpic['gesch. Zeitaufwand (h)']} h</div>
        </div>
        <div class="hidden flex-col gap-3 mt-3 ml-5" id="epic-${childEpic.IID}">
          ${subChildEpics.length > 0 ? renderChildEpics(childEpic.IID, level + 1) : ''}
          ${directIssues.length > 0 ? `<div class="flex flex-col gap-2">${directIssues.map(issue => renderIssue(issue)).join('')}</div>` : ''}
        </div>
      </div>`;
    });
    html += `</div>`;
    return html;
  }

  const repoName = groupPath.split('/').pop() || 'Repository';
  let html = '<div class="flex flex-col gap-2">';
  html += `<div class="rounded-[32px] p-5 cursor-pointer" style="background:linear-gradient(135deg, #6C63FF, #8B84FF); color:white;" onclick="toggleEpic('root')">
    <div class="font-display font-bold text-lg"><i class="fa-solid fa-box"></i> ${repoName}</div>
    <div class="text-sm mt-1 opacity-85">${root.Titel}</div>
    <div class="text-sm font-medium mt-1 opacity-75">${root['Zeitaufwand (h)']} h / ${root['gesch. Zeitaufwand (h)']} h</div>
  </div>`;
  html += `<div class="hidden flex-col gap-3 mt-3 ml-5" id="epic-root">`;
  if (topLevelEpics.length > 0) {
    html += '<div class="flex flex-col ml-4 pl-4 gap-2" style="border-left:2px solid rgba(163,177,198,0.4)">';
    topLevelEpics.forEach(epic => {
      const totalIssues = getAllIssuesForEpic(epic.IID);
      const directIssues = getDirectIssues(epic.IID);
      const childEpicCount = countChildEpics(epic.IID);
      html += '<div class="flex flex-col">';
      html += `<div class="neu-card-inset p-4 cursor-pointer tree-node-content" onclick="toggleEpic(${epic.IID})">
        <div class="font-display font-semibold text-[#3D4852]"><i class="fa-regular fa-folder-open text-[#6C63FF]"></i> ${epic.Titel}</div>
        <div class="text-xs text-[#6B7280] mt-1">
          ${childEpicCount > 0 ? `${childEpicCount} Child-Epic${childEpicCount > 1 ? 's' : ''} | ` : ''}
          ${totalIssues.length} Issue${totalIssues.length !== 1 ? 's' : ''}
        </div>
        <div class="text-xs font-medium text-[#3D4852]">${epic['Zeitaufwand (h)']} h / ${epic['gesch. Zeitaufwand (h)']} h</div>
      </div>`;
      html += `<div class="hidden flex-col gap-3 mt-3 ml-5" id="epic-${epic.IID}">
        ${renderChildEpics(epic.IID, 1)}
        ${directIssues.length > 0 ? `<div class="flex flex-col gap-2">${directIssues.map(issue => renderIssue(issue)).join('')}</div>` : ''}
      </div></div>`;
    });
    html += '</div>';
  }
  html += '</div></div>';
  container.innerHTML = html;
}

function toggleEpic(epicId) {
  const epicContent = document.getElementById(`epic-${epicId}`);
  if (!epicContent) return;
  if (epicContent.classList.contains('flex')) {
    epicContent.classList.remove('flex', 'flex-col', 'gap-3', 'mt-3', 'ml-5');
    epicContent.classList.add('hidden');
  } else {
    epicContent.classList.remove('hidden');
    epicContent.classList.add('flex', 'flex-col', 'gap-3', 'mt-3', 'ml-5');
  }
}

async function loadReports() {
  try {
    const response = await fetch('/api/reports');
    const result = await response.json();
    const listDiv = document.getElementById('reportsList');
    if (!result.success || result.reports.length === 0) {
      listDiv.innerHTML = '<p class="text-center py-6 text-[#6B7280]">Keine Berichte vorhanden</p>';
      return;
    }
    listDiv.innerHTML = result.reports.map(report => {
      const dateStr = report.created.split(' ')[0];
      return `<div class="neu-card-inset p-5 cursor-pointer" onclick="viewReport('${report.filename}')">
        <div class="font-display font-semibold text-[#3D4852] mb-3 text-sm flex items-center gap-2"><i class="fa-regular fa-file-lines text-[#6C63FF]"></i> Bericht vom ${dateStr}</div>
        <div class="flex gap-2 text-xs">
          <span class="neu-tag"><i class="fa-regular fa-calendar"></i> ${report.created}</span>
          <span class="neu-tag"><i class="fa-solid fa-chart-bar"></i> ${(report.size / 1024).toFixed(2)} KB</span>
        </div>
      </div>`;
    }).join('');
  } catch (error) {
    console.error('Error loading reports:', error);
    document.getElementById('reportsList').innerHTML = '<p class="text-center py-6 text-[#6B7280]">Fehler beim Laden der Berichte</p>';
  }
}

async function generateReport() {
  const btn = document.getElementById('generateReportBtn');
  btn.disabled = true;
  btn.innerHTML = '<i class="fa-solid fa-hourglass-half"></i> Bericht wird erstellt...';
  try {
    const response = await fetch('/api/generate-report', { method: 'POST', headers: { 'Content-Type': 'application/json' } });
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`Server error: ${response.status} - ${errorText}`);
    }
    const result = await response.json();
    if (result.success) {
      alert('✅ Bericht erfolgreich erstellt!');
      loadReports();
    } else {
      alert('❌ Fehler beim Erstellen des Berichts: ' + result.error);
    }
  } catch (error) {
    console.error('Error generating report:', error);
    alert('❌ Fehler beim Erstellen des Berichts: ' + error.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="fa-regular fa-pen-to-square"></i> Bericht jetzt erstellen';
  }
}

function viewReport(filename) {
  const modal = document.getElementById('reportModal');
  const contentDiv = document.getElementById('reportContent');
  contentDiv.innerHTML = '<p class="text-center text-[#6B7280] py-8">Lade Bericht...</p>';
  modal.classList.remove('hidden');
  modal.classList.add('flex');
  fetch(`/reports/${filename}`)
    .then(response => response.text())
    .then(html => { contentDiv.innerHTML = html; })
    .catch(error => {
      console.error('Error loading report:', error);
      contentDiv.innerHTML = '<p class="text-center text-red-500 py-8">Fehler beim Laden des Berichts</p>';
    });
}

function closeReportModal() {
  const modal = document.getElementById('reportModal');
  modal.classList.add('hidden');
  modal.classList.remove('flex');
}

function createLeaderboard(userStats, userIssueCount) {
  const container = document.getElementById('leaderboardContainer');
  userIssueCount = userIssueCount || {};
  const users = Object.keys(userStats).filter(u => userStats[u] > 0);
  if (users.length === 0) {
    container.innerHTML = '<p class="text-[#6B7280] text-center py-6">Keine Daten verfügbar</p>';
    return;
  }
  users.sort((a, b) => userStats[b] - userStats[a]);
  const maxHours = userStats[users[0]] || 1;
  const totalHours = users.reduce((s, u) => s + userStats[u], 0);

  const medals = ['🥇', '🥈', '🥉'];
  const rankColors = ['#FFD700', '#C0C0C0', '#CD7F32'];

  let html = '<div class="flex flex-col gap-3">';
  users.forEach((user, i) => {
    const hours = userStats[user];
    const pct = ((hours / totalHours) * 100).toFixed(1);
    const barPct = (hours / maxHours) * 100;
    const issueCount = userIssueCount[user] || 0;
    const rank = i + 1;
    const isTop3 = i < 3;

    let rankBadge = '';
    if (isTop3) {
      rankBadge = `<span style="font-size:1.5rem;line-height:1">${medals[i]}</span>`;
    } else {
      rankBadge = `<span class="font-display font-bold text-sm text-[#8B95A5]" style="width:28px;text-align:center;display:inline-block">${rank}</span>`;
    }

    const rowClass = isTop3
      ? 'neu-card-inset p-4 flex items-center gap-4'
      : 'neu-card-inset p-3 flex items-center gap-4';
    const borderAccent = isTop3 ? `style="border-left:4px solid ${rankColors[i]}"` : '';

    html += `<div class="${rowClass}" ${borderAccent}>
      <div class="flex-shrink-0 flex items-center justify-center" style="width:36px">
        ${rankBadge}
      </div>
      <div class="flex-shrink-0 w-9 h-9 rounded-full flex items-center justify-center font-display font-bold text-sm" style="background:linear-gradient(135deg, #6C63FF, #8B84FF);color:white">
        ${user.charAt(0).toUpperCase()}
      </div>
      <div class="flex-1 min-w-0">
        <div class="font-display font-semibold text-sm text-[#3D4852] truncate">${user}</div>
        <div class="w-full h-2 rounded-full mt-1.5" style="background:var(--bg);box-shadow:inset 2px 2px 4px rgb(163,177,198,0.6), inset -2px -2px 4px rgba(255,255,255,0.5)">
          <div class="h-full rounded-full" style="width:${barPct}%;background:linear-gradient(90deg, #6C63FF, #8B84FF);transition:width 600ms ease-out"></div>
        </div>
      </div>
      <div class="flex-shrink-0 text-right min-w-[100px]">
        <div class="font-display font-bold text-base text-[#3D4852]">${hours.toFixed(1)} h</div>
        <div class="text-xs text-[#6B7280]">${pct}%</div>
      </div>
      <div class="flex-shrink-0 text-center min-w-[60px] hidden sm:block">
        <div class="text-xs text-[#6B7280]">Issues</div>
        <div class="font-display font-semibold text-sm text-[#3D4852]">${issueCount}</div>
      </div>
    </div>`;
  });
  html += '</div>';
  container.innerHTML = html;
}

function createUserLabelMatrixTable(matrix) {
  const container = document.getElementById('userLabelMatrixContainer');
  if (!matrix || Object.keys(matrix).length === 0) {
    container.innerHTML = '<p class="text-[#6B7280] text-center py-6">Keine Daten verfügbar</p>';
    return;
  }
  const users = Object.keys(matrix).sort();
  const labels = Object.keys(matrix[users[0]] || {}).sort();
  let html = '<table class="w-full border-collapse text-sm">';
  html += '<thead><tr>';
  html += '<th class="p-3 text-left font-display font-semibold text-xs text-[#6B7280] neu-inset-sm" style="border-radius:12px 0 0 0">User</th>';
  labels.forEach(label => {
    html += `<th class="p-3 text-center font-display font-semibold text-xs text-[#6B7280] neu-inset-sm">${label}</th>`;
  });
  html += '<th class="p-3 text-center font-display font-semibold text-xs text-[#6B7280] neu-inset-sm" style="border-radius:0 12px 0 0">Gesamt</th>';
  html += '</tr></thead><tbody>';
  users.forEach((user, ui) => {
    let userTotal = 0;
    html += `<tr><td class="p-3 text-left font-semibold text-[#3D4852] neu-inset-sm">${user}</td>`;
    labels.forEach(label => {
      const value = matrix[user][label] || 0;
      userTotal += value;
      const displayValue = value > 0 ? value.toFixed(2) + ' h' : '-';
      const cls = value === 0
        ? 'p-3 text-center font-medium text-[#8B95A5] neu-inset-sm'
        : 'p-3 text-center font-medium neu-inset-sm';
      html += `<td class="${cls}">${displayValue}</td>`;
    });
    html += `<td class="p-3 text-center font-bold text-[#6C63FF] neu-inset-sm">${userTotal.toFixed(2)} h</td></tr>`;
  });
  html += '</tbody></table>';
  container.innerHTML = html;
}

document.addEventListener('DOMContentLoaded', () => {
  window.addEventListener('click', event => {
    if (event.target == document.getElementById('reportModal')) closeReportModal();
  });

  const filterBar = document.getElementById('filterBar');
  let filterBarStuck = false;
  window.addEventListener('scroll', () => {
    const header = document.querySelector('header');
    if (!header) return;
    const headerBottom = header.offsetTop + header.offsetHeight;
    const shouldStick = window.scrollY > headerBottom - filterBar.offsetHeight;
    if (shouldStick !== filterBarStuck) {
      filterBarStuck = shouldStick;
      filterBar.classList.toggle('stuck', shouldStick);
    }
  }, { passive: true });

  loadData(currentFilter, false);
  loadReports();
});
