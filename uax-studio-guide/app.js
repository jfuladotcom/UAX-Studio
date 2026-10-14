/* Standalone presentation controller. All data stays in this page's memory. */
(() => {
  'use strict';
  const data = window.UAX_GUIDE;
  if (!data || !Array.isArray(data.slides) || !data.slides.length) return;
  const slides = data.slides;
  const $ = id => document.getElementById(id);
  const stage = $('slide-stage');
  const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let index = 0, readerMode = false, toastTimer;
  stage.innerHTML = slides.map((slide,i) => `<section id="${escape(slide.id)}" class="slide ${escape(slide.className || '')}" data-slide-index="${i}" aria-label="Slide ${i+1}: ${escape(slide.title)}" hidden><div class="slide-inner">${slide.html}</div><span class="slide-number-print">UAX Studio guide · ${i+1} / ${slides.length}</span></section>`).join('');
  const sections = Array.from(stage.children);
  function toast(message){ $('toast').textContent=message; $('toast').classList.add('visible'); clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('toast').classList.remove('visible'),2500); }
  function closeDialogs(){ document.querySelectorAll('dialog[open]').forEach(dialog=>dialog.close()); }
  function openDialog(id){ closeDialogs(); $(id).showModal(); }
  function renderOutline(query=''){
    const q=query.trim().toLowerCase();
    const matching=slides.map((slide,i)=>({slide,i})).filter(({slide})=>(slide.title+' '+slide.chapter+' '+(slide.tags||'')).toLowerCase().includes(q));
    const groups = [...new Set(matching.map(({slide})=>slide.chapter))];
    $('slide-outline').innerHTML=groups.map(chapter=>`<section class="outline-section"><h3>${escape(chapter)}</h3>${matching.filter(({slide})=>slide.chapter===chapter).map(({slide,i})=>`<a class="outline-link" href="#${escape(slide.id)}" ${i===index?'aria-current="page"':''}><span>${String(i+1).padStart(2,'0')}</span>${escape(slide.title)}</a>`).join('')}</section>`).join('');
    $('search-status').textContent=q?`${matching.length} ${matching.length===1?'slide':'slides'} found`:'';
  }
  function updateChrome(){
    const slide=slides[index];
    sections.forEach((section,i)=>section.setAttribute('aria-current',i===index?'step':'false'));
    $('progress-fill').style.width=((index+1)/slides.length*100)+'%';
    $('chapter-label').textContent=slide.chapter;
    $('slide-counter').textContent=`${String(index+1).padStart(2,'0')} / ${slides.length}`;
    $('slide-counter').setAttribute('aria-label',`Slide ${index+1} of ${slides.length}. Choose a slide`);
    $('previous-button').disabled=index===0;
    $('next-button').disabled=index===slides.length-1;
    $('next-button').innerHTML=index===slides.length-1?'Complete <span aria-hidden="true">✓</span>':'Next <span aria-hidden="true">→</span>';
    $('slide-announcement').textContent=`Slide ${index+1} of ${slides.length}. ${slide.title}`;
    document.title=`${slide.title} · UAX Studio guide`;
  }
  function show(next,{focus=false,scroll=true,writeHash=true}={}){
    index=Math.max(0,Math.min(slides.length-1,next));
    sections.forEach((section,i)=>{section.hidden=!readerMode&&i!==index;section.setAttribute('aria-current',i===index?'step':'false');});
    updateChrome();
    if(writeHash){try{history.replaceState(null,'','#'+slides[index].id);}catch{location.hash=slides[index].id;}}
    if(scroll){if(readerMode) sections[index].scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});else window.scrollTo({top:0,behavior:'instant'});}
    if(focus){const title=sections[index].querySelector('h1,h2');if(title){title.tabIndex=-1;title.focus({preventScroll:true});}}
  }
  function showFromHash(){let id;try{id=decodeURIComponent(location.hash.slice(1));}catch{id='';}const next=slides.findIndex(slide=>slide.id===id);show(next<0?0:next,{writeHash:next<0});}
  function outline(){renderOutline();$('slide-search').value='';openDialog('outline-dialog');$('slide-search').focus();}
  function notes(){const slide=slides[index];$('notes-title').textContent=slide.title;$('notes-content').innerHTML=slide.notes||'<p>Follow the instructions on this slide, then continue.</p>';openDialog('notes-dialog');}
  async function fullscreen(){
    try{if(document.fullscreenElement){await document.exitFullscreen();}else if(document.documentElement.requestFullscreen){await document.documentElement.requestFullscreen();}else{toast('Full screen is unavailable in this browser.');}}
    catch{toast('Use your browser’s full screen command.');}
  }
  function toggleReader(){readerMode=!readerMode;document.body.classList.toggle('reader-mode',readerMode);$('reader-button').setAttribute('aria-pressed',String(readerMode));$('reader-button').textContent=readerMode?'Slide view':'Read all';show(index,{scroll:readerMode});toast(readerMode?'All slides are visible. Scroll to read.':'Presentation mode');}
  async function copy(text){
    try{if(!navigator.clipboard?.writeText)throw new Error('Clipboard unavailable');await navigator.clipboard.writeText(text);toast('Example copied');}
    catch{openDialog('copy-dialog');$('copy-fallback').value=text;$('copy-fallback').focus();$('copy-fallback').select();}
  }
  $('next-button').addEventListener('click',()=>show(index+1,{focus:true}));
  $('previous-button').addEventListener('click',()=>show(index-1,{focus:true}));
  $('slide-counter').addEventListener('click',outline);
  $('outline-button').addEventListener('click',outline);
  $('notes-button').addEventListener('click',notes);
  $('reader-button').addEventListener('click',toggleReader);
  $('fullscreen-button').addEventListener('click',fullscreen);
  $('shortcuts-button').addEventListener('click',()=>openDialog('shortcuts-dialog'));
  $('print-button').addEventListener('click',()=>{closeDialogs();window.print();});
  $('slide-search').addEventListener('input',event=>renderOutline(event.target.value));
  window.addEventListener('hashchange',showFromHash);
  document.addEventListener('fullscreenchange',()=>{const active=!!document.fullscreenElement;$('fullscreen-button').setAttribute('aria-label',active?'Exit full screen':'Enter full screen');$('fullscreen-button').title=active?'Exit full screen (F)':'Full screen (F)';});
  document.addEventListener('click',event=>{
    const close=event.target.closest('[data-close-dialog]');if(close){close.closest('dialog').close();return;}
    const anchor=event.target.closest('a[href^="#"]');
    if(anchor){const next=slides.findIndex(slide=>'#'+slide.id===anchor.getAttribute('href'));if(next>=0){event.preventDefault();closeDialogs();show(next,{focus:true});return;}}
    const copyButton=event.target.closest('[data-copy]');if(copyButton){const target=$(copyButton.dataset.copy);if(target)copy(target.innerText||target.textContent);return;}
    const tab=event.target.closest('[data-demo-tab]');
    if(tab){const demo=tab.closest('[data-demo]');demo.querySelectorAll('[data-demo-tab]').forEach(t=>{const chosen=t===tab;t.setAttribute('aria-selected',String(chosen));t.tabIndex=chosen?0:-1;});demo.querySelectorAll('[data-demo-panel]').forEach(p=>p.hidden=p.dataset.demoPanel!==tab.dataset.demoTab);return;}
    const workspace=event.target.closest('[data-workspace]');
    if(workspace){const demo=workspace.closest('.ui-illustration');demo.querySelectorAll('[data-workspace]').forEach(b=>b.setAttribute('aria-pressed',String(b===workspace)));const detail=data.workspace[workspace.dataset.workspace];demo.querySelector('.demo-workspace').innerHTML=`<p class="overline">${escape(detail.label)}</p><h3>${escape(detail.title)}</h3><p>${escape(detail.text)}</p><a href="#${escape(detail.slide)}" class="text-link">Jump to this lesson</a>`;return;}
    const toggle=event.target.closest('[data-guidance-demo]');if(toggle){const on=toggle.getAttribute('aria-checked')!=='true';toggle.setAttribute('aria-checked',String(on));toggle.querySelector('.switch-label').textContent=on?'On':'Off';const demo=toggle.closest('.ui-illustration');demo.querySelector('[data-guidance-status]').textContent=on?'Guidance shows a suggested next step.':'Guidance is off. Help remains available.';return;}
    if(event.target===event.target.closest('dialog')){const rect=event.target.getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)event.target.close();}
  });
  document.addEventListener('keydown',event=>{
    const tab=event.target.closest('[data-demo-tab]');
    if(tab&&['ArrowRight','ArrowLeft','Home','End'].includes(event.key)){const tabs=[...tab.closest('[role=tablist]').querySelectorAll('[data-demo-tab]')];let i=tabs.indexOf(tab);i=event.key==='Home'?0:event.key==='End'?tabs.length-1:(i+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;event.preventDefault();tabs[i].click();tabs[i].focus();return;}
    if(event.ctrlKey||event.metaKey||event.altKey||event.target.closest('input,textarea,select,[contenteditable=true]')||document.querySelector('dialog[open]'))return;
    if(event.target.closest('button,a,summary')&&[' ','Enter'].includes(event.key))return;
    const key=event.key.toLowerCase();
    if(key==='arrowright'||key==='pagedown'||(key===' '&&!readerMode)){event.preventDefault();show(index+1,{focus:true});}
    else if(key==='arrowleft'||key==='pageup'){event.preventDefault();show(index-1,{focus:true});}
    else if(key==='home'){event.preventDefault();show(0,{focus:true});}
    else if(key==='end'){event.preventDefault();show(slides.length-1,{focus:true});}
    else if(key==='c')outline();else if(key==='n')notes();else if(key==='f')fullscreen();else if(key==='?')openDialog('shortcuts-dialog');
  });
  // Keep the notes and counter aligned with the visible section in Read all.
  if('IntersectionObserver' in window){const observer=new IntersectionObserver(entries=>{if(!readerMode)return;const visible=entries.filter(entry=>entry.isIntersecting).sort((a,b)=>b.intersectionRatio-a.intersectionRatio);if(visible.length){index=Number(visible[0].target.dataset.slideIndex);updateChrome();}}, {rootMargin:'-80px 0px -20% 0px',threshold:[0,.2,.5,.8]});sections.forEach(section=>observer.observe(section));}
  showFromHash();
})();
