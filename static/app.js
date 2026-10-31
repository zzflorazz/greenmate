/* Shared transport, notices and navigation. No page-specific DOM here. */
(() => {
'use strict';
const $=id=>document.getElementById(id);
function notice(id,message='',error=false){const node=$(id);if(!node)return;node.textContent=message;node.className='notice '+(error?'error':'success');}
function errorText(error){return error.message||'请求失败，请稍后重试。';}
async function request(path,options={}){let response;try{response=await fetch(path,{...options,headers:{'Content-Type':'application/json',...options.headers}});}catch{throw new Error('无法连接服务，请检查网络和 GreenMate 是否已启动。');}let data;try{data=await response.json();}catch{throw new Error('服务返回了无法识别的内容，请稍后重试。');}if(!response.ok||data.error&&typeof data.error==='object'){const info=data.error;const err=new Error(info&&info.message?info.message+'\n'+info.hint:(data.detail||data.llm_error?.message||'服务暂不可用，请稍后重试。'));err.data=data;throw err;}return data;}
function post(path,body){return request(path,{method:'POST',body:JSON.stringify(body)});}
async function action(button,status,task){if(!button)return;button.disabled=true;notice(status,'正在处理，请稍候…');try{await task();}catch(error){notice(status,errorText(error),true);}finally{button.disabled=false;}}
function badge(text,type=''){const span=document.createElement('span');span.className='badge '+type;span.textContent=text;return span;}

window.GM={ $,request,post,action,notice,badge,errorText };
const reduced=matchMedia('(prefers-reduced-motion: reduce)');
for(const image of document.querySelectorAll('.photo img')){
 const fallback=()=>{const box=image.closest('.photo');if(box)box.classList.add('img-fallback');};
 image.addEventListener('error',fallback);if(image.complete&&!image.naturalWidth)fallback();
}
let navigating=false;
addEventListener('pageshow',()=>{navigating=false;document.documentElement.classList.remove('is-leaving');});
for(const link of document.querySelectorAll('a[href]'))link.addEventListener('click',event=>{
 if(event.defaultPrevented||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey||link.target||link.hasAttribute('download'))return;
 const url=new URL(link.href,location.href);
 if(url.origin!==location.origin||url.pathname===location.pathname||reduced.matches||!document.startViewTransition)return;
 event.preventDefault();if(navigating)return;navigating=true;
 // Finish the native same-document exit before full navigation: navigating
 // inside its callback would abort the transition and log a browser error.
 try{const transition=document.startViewTransition(()=>{document.documentElement.classList.add('is-leaving');});transition.finished.catch(()=>{}).then(()=>location.assign(url.href));}catch{location.assign(url.href);}
});
const banners=[...document.querySelectorAll('.page-banner')];
let frame=0;
function parallax(){frame=0;for(const banner of banners){const image=banner.querySelector('img');if(!image)continue;const y=reduced.matches?0:Math.max(-24,Math.min(24,-banner.getBoundingClientRect().top*.08));image.style.transform=`translateY(${y}px)`;}}
if(banners.length){addEventListener('scroll',()=>{if(!reduced.matches&&!frame)frame=requestAnimationFrame(parallax)},{passive:true});reduced.addEventListener('change',parallax);parallax();}
})();
