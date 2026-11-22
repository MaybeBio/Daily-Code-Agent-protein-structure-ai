import './style.css';
import './workbench.css';
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { datasets } from './datasets.js';

gsap.registerPlugin(ScrollTrigger);
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
const loader = document.querySelector('.loader');
let world, disposed = false;
const reveal = () => {
  if (loader.hidden) return;
  if (reduced) loader.hidden = true;
  else gsap.to(loader, { yPercent: -100, duration: .8, ease: 'power3.inOut', onComplete: () => { loader.hidden = true; } });
};
const timeout = setTimeout(reveal, 3500);
import('./scene.js').then(({ createWorld }) => {
  if (!disposed) world = createWorld(document.querySelector('#world'), reduced);
}).catch(() => document.body.classList.add('fallback')).finally(() => { clearTimeout(timeout); reveal(); });

const menu = document.querySelector('#menu');
const menuButton = document.querySelector('.menu-button');
const main = document.querySelector('main');
const footer = document.querySelector('footer');
function setMenu(open) {
  menu.hidden = !open;
  menuButton.setAttribute('aria-expanded', String(open));
  main.inert = open; footer.inert = open;
  document.body.style.overflow = open ? 'hidden' : '';
  if (open) {
    menu.scrollTop = 0;
    if (!reduced) gsap.fromTo(menu.querySelectorAll('a'), { y: 35, opacity: 0 }, { y: 0, opacity: 1, stagger: .07, duration: .5 });
    menu.querySelector('a').focus();
  } else menuButton.focus();
}
menuButton.addEventListener('click', () => setMenu(menu.hidden));
document.addEventListener('keydown', event => {
  if (menu.hidden) return;
  if (event.key === 'Escape') setMenu(false);
  if (event.key === 'Tab') {
    const items = [menuButton, ...menu.querySelectorAll('a')];
    const index = items.indexOf(document.activeElement);
    if (event.shiftKey && index <= 0) { event.preventDefault(); items.at(-1).focus(); }
    else if (!event.shiftKey && index === items.length - 1) { event.preventDefault(); menuButton.focus(); }
  }
});

const dialog = document.querySelector('#project-dialog');
let lastCard, selectedDataset, transition;
function syncRoute() {
  const id = location.hash.replace('#dataset/', '');
  const data = datasets.find(item => item.id === id);
  if (data) {
    selectedDataset = data.id;
    document.querySelector('#dialog-title').textContent = data.name;
    document.querySelector('#dialog-copy').textContent = data.text;
    document.querySelector('#dialog-detail').textContent = data.detail;
    if (!dialog.open) dialog.showModal();
  } else if (dialog.open) dialog.close();
}
document.querySelectorAll('[data-project]').forEach(card => card.addEventListener('click', () => {
  lastCard = card;
  history.pushState({ dataset: true }, '', `#dataset/${card.dataset.project}`);
  syncRoute();
}));
function closeDetails() {
  if (history.state?.dataset) history.back();
  else { history.replaceState(null, '', '#research'); syncRoute(); }
}
document.querySelector('.dialog-close').addEventListener('click', closeDetails);
dialog.addEventListener('cancel', event => { event.preventDefault(); closeDetails(); });
dialog.addEventListener('click', event => {
  if (event.target !== dialog) return;
  const bounds = dialog.getBoundingClientRect();
  if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) closeDetails();
});
dialog.addEventListener('close', () => lastCard?.focus());
window.addEventListener('popstate', syncRoute);
window.addEventListener('hashchange', syncRoute);
syncRoute();

document.querySelector('#dialog-explore').addEventListener('click', () => {
  const select = document.querySelector('#dataset');
  if (selectedDataset && select.value !== selectedDataset) {
    select.value = selectedDataset;
    select.dispatchEvent(new Event('change', { bubbles: true }));
  }
});

document.querySelectorAll('a[href^="#"]').forEach(link => link.addEventListener('click', event => {
  const hash = link.getAttribute('href');
  if (!hash || hash === '#') return;
  const target = document.getElementById(hash.slice(1));
  if (!target) return;
  event.preventDefault();
  if (!menu.hidden) setMenu(false);
  if (dialog.open) dialog.close();
  transition?.kill();
  const go = () => {
    if (target.tagName === 'DETAILS') target.open = true;
    history.pushState(null, '', hash);
    target.scrollIntoView({ behavior: 'instant', block: 'start' });
    target.setAttribute('tabindex', '-1'); target.focus({ preventScroll: true });
    window.dispatchEvent(new Event('resize'));
  };
  if (reduced) go();
  else transition = gsap.timeline()
    .set('.transition', { visibility: 'visible' })
    .to('.transition', { yPercent: -101, duration: .35, ease: 'power3.inOut' })
    .call(go)
    .to('.transition', { yPercent: -202, duration: .45, ease: 'power3.inOut' })
    .set('.transition', { yPercent: 0, visibility: 'hidden' });
}));

document.querySelectorAll('[data-filter]').forEach(button => button.addEventListener('click', () => {
  document.querySelectorAll('[data-filter]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
  document.querySelectorAll('.card').forEach(card => {
    card.hidden = button.dataset.filter !== 'All' && card.dataset.category !== button.dataset.filter;
  });
  ScrollTrigger.refresh();
}));

const animations = gsap.context(() => {
  if (!reduced) {
    gsap.from('.hero h1 span', { yPercent: 40, opacity: 0, stagger: .13, duration: 1.2, delay: .8, ease: 'power3.out' });
    document.querySelectorAll('.intro h2,.section-heading').forEach(element => gsap.from(element, {
      clipPath: 'inset(0 0 100% 0)', y: 35, duration: 1,
      scrollTrigger: { trigger: element, start: 'top 90%', once: true }
    }));
    gsap.to('.hero h1', { y: -110, scrollTrigger: { trigger: '.hero', start: 'top top', end: 'bottom top', scrub: true } });
  }
  ScrollTrigger.create({ start: 0, end: 'max', onUpdate: self => {
    document.querySelector('.progress').style.transform = `scaleX(${self.progress})`;
    world?.setProgress(Math.min(scrollY / innerHeight, 1));
    document.querySelector('.status').style.opacity = scrollY < innerHeight * .6 ? '1' : '0';
  } });
});
// Saved pair links open the actual model workspace rather than hiding results below the hero.
if (new URLSearchParams(location.search).has('pair')) {
  document.querySelector('#workspace').scrollIntoView({ behavior: 'instant' });
}
if (import.meta.hot) import.meta.hot.dispose(() => {
  disposed = true; clearTimeout(timeout); world?.dispose(); animations.revert(); transition?.kill();
  window.removeEventListener('popstate', syncRoute); window.removeEventListener('hashchange', syncRoute);
});
