export interface HardwareSummaryRow {
  property: string;
  scout: string;
  responder: string;
}

export const FALLBACK_HARDWARE_SUMMARY: HardwareSummaryRow[] = [
  { property: 'Base', scout: 'AgileX LIMO Pro', responder: 'Clearpath Jackal' },
  { property: 'Size (L x W x H)', scout: '322 x 220 x 251 mm', responder: '508 x 430 x 250 mm base; about 700 mm high with the LiDAR mast (estimate)' },
  { property: 'Weight', scout: '4.8 kg base; about 5.2 kg with add-ons (estimate)', responder: '17 kg base; about 26 kg with arm, sensors, compute and supplies (estimate)' },
  { property: 'Compute', scout: 'NVIDIA Jetson Orin Nano (built in)', responder: 'NVIDIA Jetson Orin NX 16GB' },
  { property: 'LiDAR', scout: 'EAI YDLIDAR T-mini Pro, 2D, 360 degrees, 12 m', responder: 'Livox Mid-360, 3D, 360 x 59 degrees, 40 m at 10% reflectivity' },
  { property: 'Camera', scout: 'Orbbec DaBai depth camera (built in)', responder: 'Luxonis OAK-D Lite (RGB + stereo depth)' },
  { property: 'Thermal', scout: 'Teledyne FLIR Lepton 3.5, 160 x 120', responder: 'Teledyne FLIR Lepton 3.5, 160 x 120' },
  { property: 'Microphones', scout: 'Seeed ReSpeaker Mic Array v2.0 (4 mics, direction of arrival)', responder: 'Seeed ReSpeaker Mic Array v2.0 (also the casualty speaker/mic for the guide voice)' },
  { property: 'IMU', scout: 'CEVA BNO085 (added)', responder: 'Jackal onboard IMU, plus CEVA BNO085' },
  { property: 'Arm', scout: 'none', responder: 'Kinova Gen3 lite, 6 DoF, 0.5 kg payload, 760 mm reach' },
  { property: 'Battery', scout: '12 V, 10 Ah (120 Wh)', responder: '270 Wh lithium' },
  { property: 'Runtime', scout: '2.5 h working (maker); about 2.3 h with add-ons (estimate)', responder: '2 h heavy use to 8 h basic use (maker); about 2 h on a rescue run (estimate)' },
  { property: 'Units', scout: '2 in a full deployment (the demo simulates 1)', responder: '1' }
];

export function parseHardwareSummaryTable(markdown: string): HardwareSummaryRow[] {
  const lines = markdown.split(/\r?\n/);
  const rows: HardwareSummaryRow[] = [];
  let inSummary = false;
  let passedHeader = 0;

  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed.startsWith('## Summary')) {
      inSummary = true;
      passedHeader = 0;
      continue;
    }
    if (inSummary) {
      if (trimmed.startsWith('## ') && !trimmed.startsWith('## Summary')) {
        break;
      }
      if (!trimmed.startsWith('|')) continue;
      const cols = trimmed
        .split('|')
        .map(c => c.trim())
        .filter((_, idx, arr) => idx > 0 && idx < arr.length - 1);

      if (cols.length >= 3) {
        if (passedHeader < 2) {
          passedHeader++;
          continue;
        }
        rows.push({
          property: cols[0],
          scout: cols[1],
          responder: cols[2]
        });
      }
    }
  }

  return rows.length > 0 ? rows : FALLBACK_HARDWARE_SUMMARY;
}

function renderValueWithEstimates(text: string): string {
  return text.replace(/\(estimate\)/gi, '<span class="badge-estimate">estimate</span>');
}

export function populateHardwareTable(tbody: HTMLElement, rows: HardwareSummaryRow[]): void {
  tbody.innerHTML = '';
  for (const row of rows) {
    const tr = document.createElement('tr');
    tr.dataset.property = row.property;

    const tdProp = document.createElement('td');
    tdProp.className = 'hw-prop';
    tdProp.textContent = row.property;

    const tdScout = document.createElement('td');
    tdScout.className = 'hw-scout';
    tdScout.innerHTML = renderValueWithEstimates(row.scout);

    const tdResp = document.createElement('td');
    tdResp.className = 'hw-responder';
    tdResp.innerHTML = renderValueWithEstimates(row.responder);

    tr.appendChild(tdProp);
    tr.appendChild(tdScout);
    tr.appendChild(tdResp);
    tbody.appendChild(tr);
  }
}

export function setupHardwarePanel(): void {
  const btnOpen = document.querySelector<HTMLButtonElement>('#btn-hardware-specs');
  const dialog = document.querySelector<HTMLDialogElement>('#hardware-dialog');
  const btnClose = document.querySelector<HTMLButtonElement>('#btn-close-hardware');
  const tbody = document.querySelector<HTMLElement>('#hardware-tbody');

  if (!dialog || !tbody) return;

  // Initialize with fallback
  populateHardwareTable(tbody, FALLBACK_HARDWARE_SUMMARY);

  // Try fetching hardware.md or hardware.json if available
  fetch('/fixtures/hardware.json')
    .then(r => r.ok ? r.json() : Promise.reject())
    .then((data: HardwareSummaryRow[]) => {
      if (Array.isArray(data) && data.length > 0) {
        populateHardwareTable(tbody, data);
      }
    })
    .catch(() => {
      fetch('/fixtures/hardware.md')
        .then(r => r.ok ? r.text() : Promise.reject())
        .then(md => populateHardwareTable(tbody, parseHardwareSummaryTable(md)))
        .catch(() => {
          // Keep fallback
        });
    });

  btnOpen?.addEventListener('click', () => {
    dialog.showModal();
  });

  btnClose?.addEventListener('click', () => {
    dialog.close();
  });

  dialog.addEventListener('click', event => {
    if (event.target === dialog) {
      dialog.close();
    }
  });
}
