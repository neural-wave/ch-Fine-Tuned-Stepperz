const form = document.querySelector('#query-form');
const question = document.querySelector('#question');
const submitButton = document.querySelector('#submit-button');
const count = document.querySelector('#char-count');
const processFooter = document.querySelector('#process-footer');
const processMessage = document.querySelector('#process-message');
const elapsed = document.querySelector('#elapsed');
const stages = [...document.querySelectorAll('#process-list li')];
const resultSection = document.querySelector('#result-section');
const verdictPanel = document.querySelector('#verdict-panel');
const reasonPanel = document.querySelector('#reason-panel');
const queryOutput = document.querySelector('#query-output');
const copyButton = document.querySelector('#copy-button');
let timer = null;
let startedAt = 0;

const setText = (selector, value) => {
  document.querySelector(selector).textContent = value;
};

function setStage(element, state, label) {
  element.classList.remove('running', 'done', 'blocked');
  if (state) element.classList.add(state);
  element.querySelector('.stage-state').textContent = label;
}

function resetResult() {
  resultSection.hidden = true;
  reasonPanel.hidden = true;
  verdictPanel.classList.remove('blocked', 'error');
  queryOutput.textContent = '';
  copyButton.hidden = false;
  for (const stage of stages) setStage(stage, '', 'READY');
}

function startWaiting() {
  resetResult();
  document.querySelector('#process-list').setAttribute('aria-busy', 'true');
  submitButton.disabled = true;
  submitButton.firstChild.textContent = 'Working through checks ';
  processFooter.classList.remove('complete');
  processFooter.classList.add('busy');
  processMessage.textContent = 'Processing your question · exact stages confirmed on return';
  for (const stage of stages) setStage(stage, 'running', 'IN FLOW');
  startedAt = performance.now();
  elapsed.textContent = '0.0 s';
  timer = window.setInterval(() => {
    elapsed.textContent = `${((performance.now() - startedAt) / 1000).toFixed(1)} s`;
  }, 100);
}

function finishWaiting(message) {
  window.clearInterval(timer);
  timer = null;
  document.querySelector('#process-list').setAttribute('aria-busy', 'false');
  submitButton.disabled = false;
  submitButton.firstChild.textContent = 'Generate & assess query ';
  processFooter.classList.remove('busy');
  processFooter.classList.add('complete');
  processMessage.textContent = message;
  elapsed.textContent = `${((performance.now() - startedAt) / 1000).toFixed(1)} s`;
}

function revealResult() {
  resultSection.hidden = false;
  resultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderSuccess(data) {
  const analytics = data.analytics || {};
  const promptDecision = analytics.prompt_decision || 'Not available';
  const analysis = analytics.query_analysis || {};
  const queryDecision = analysis.status || (data.is_compliant ? 'compliant' : 'not compliant');
  const timings = analytics.timings || {};
  const seconds = timings.request_total ?? timings.total;
  const compliant = data.is_compliant === true;

  setStage(stages[0], promptDecision === 'allow' ? 'done' : 'blocked', promptDecision.toUpperCase());
  setStage(stages[1], 'done', 'DONE');
  setStage(stages[2], analysis.is_compliant === true ? 'done' : 'blocked', queryDecision.toUpperCase().replaceAll('_', ' '));
  finishWaiting('Assessment complete');

  verdictPanel.classList.toggle('blocked', !compliant);
  setText('#verdict-mark', compliant ? '✓' : '!');
  setText('#verdict-eyebrow', compliant ? 'PREFLIGHT CHECKS PASSED' : 'PREFLIGHT CHECKS FLAGGED');
  setText('#verdict-title', compliant ? 'Ready for review.' : 'Not compliant.');
  setText('#verdict-description', compliant
    ? 'The prompt assessment and static query checks passed. Review the query before any separate, authorized execution.'
    : 'At least one request or query check did not pass. The generated query is retained below for inspection only.');
  setText('#verdict-seal', compliant ? 'REVIEW\nBEFORE\nUSE' : 'DO NOT\nEXECUTE');

  reasonPanel.hidden = compliant;
  setText('#reason-text', compliant ? '' : (data.compliance_reason || 'The request or query did not pass preflight assessment.'));
  queryOutput.textContent = data.sparql_query || '';
  copyButton.hidden = !queryOutput.textContent;
  setText('#prompt-decision', promptDecision.replaceAll('_', ' '));
  setText('#query-decision', queryDecision.replaceAll('_', ' '));
  setText('#tokens', Number.isFinite(data.tokens_consumed) ? new Intl.NumberFormat().format(data.tokens_consumed) : '—');
  setText('#total-time', Number.isFinite(seconds) ? `${seconds.toFixed(2)} s` : '—');
  setText('#result-id', analytics.request?.id ? `RUN ${analytics.request.id.slice(0, 8).toUpperCase()}` : 'CURRENT RUN');
  revealResult();
}

function renderError(message) {
  for (const stage of stages) setStage(stage, '', 'NOT VERIFIED');
  finishWaiting('Assessment could not be completed');
  verdictPanel.classList.add('error');
  setText('#verdict-mark', '×');
  setText('#verdict-eyebrow', 'WORKFLOW INTERRUPTED');
  setText('#verdict-title', 'No verdict available.');
  setText('#verdict-description', 'The API did not complete this assessment. Try again or check the service status.');
  setText('#verdict-seal', 'NO\nVERDICT');
  reasonPanel.hidden = false;
  setText('#reason-text', message);
  queryOutput.textContent = '';
  copyButton.hidden = true;
  for (const selector of ['#prompt-decision', '#query-decision', '#tokens', '#total-time']) setText(selector, '—');
  setText('#result-id', 'INCOMPLETE RUN');
  revealResult();
}

question.addEventListener('input', () => {
  count.textContent = `${new Intl.NumberFormat().format(question.value.length)} / 16,384`;
});

question.addEventListener('keydown', event => {
  if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    form.requestSubmit();
  }
});

for (const chip of document.querySelectorAll('.example-chip')) {
  chip.addEventListener('click', () => {
    question.value = chip.dataset.prompt || '';
    question.dispatchEvent(new Event('input'));
    question.focus();
  });
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  const text = question.value.trim();
  if (!text || submitButton.disabled) return;
  startWaiting();
  try {
    const response = await fetch('/study/nl-to-sparql', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `Request failed (${response.status}).`);
    if (typeof data.sparql_query !== 'string' || typeof data.is_compliant !== 'boolean') {
      throw new Error('The API returned an incomplete assessment.');
    }
    renderSuccess(data);
  } catch (error) {
    renderError(error instanceof Error ? error.message : 'Could not reach the API.');
  }
});

copyButton.addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(queryOutput.textContent);
    copyButton.textContent = 'Copied ✓';
    window.setTimeout(() => { copyButton.textContent = 'Copy query'; }, 1800);
  } catch {
    copyButton.textContent = 'Copy unavailable';
  }
});
