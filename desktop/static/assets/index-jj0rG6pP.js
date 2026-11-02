(function(){let e=document.createElement(`link`).relList;if(e&&e.supports&&e.supports(`modulepreload`))return;for(let e of document.querySelectorAll(`link[rel="modulepreload"]`))n(e);new MutationObserver(e=>{for(let t of e)if(t.type===`childList`)for(let e of t.addedNodes)e.tagName===`LINK`&&e.rel===`modulepreload`&&n(e)}).observe(document,{childList:!0,subtree:!0});function t(e){let t={};return e.integrity&&(t.integrity=e.integrity),e.referrerPolicy&&(t.referrerPolicy=e.referrerPolicy),t.credentials=e.crossOrigin===`use-credentials`?`include`:e.crossOrigin===`anonymous`?`omit`:`same-origin`,t}function n(e){if(e.ep)return;e.ep=!0;let n=t(e);fetch(e.href,n)}})();var e=globalThis,t=e.ShadowRoot&&(e.ShadyCSS===void 0||e.ShadyCSS.nativeShadow)&&`adoptedStyleSheets`in Document.prototype&&`replace`in CSSStyleSheet.prototype,n=Symbol(),r=new WeakMap,i=class{constructor(e,t,r){if(this._$cssResult$=!0,r!==n)throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");this.cssText=e,this.t=t}get styleSheet(){let e=this.o,n=this.t;if(t&&e===void 0){let t=n!==void 0&&n.length===1;t&&(e=r.get(n)),e===void 0&&((this.o=e=new CSSStyleSheet).replaceSync(this.cssText),t&&r.set(n,e))}return e}toString(){return this.cssText}},a=e=>new i(typeof e==`string`?e:e+``,void 0,n),o=(n,r)=>{if(t)n.adoptedStyleSheets=r.map(e=>e instanceof CSSStyleSheet?e:e.styleSheet);else for(let t of r){let r=document.createElement(`style`),i=e.litNonce;i!==void 0&&r.setAttribute(`nonce`,i),r.textContent=t.cssText,n.appendChild(r)}},s=t?e=>e:e=>e instanceof CSSStyleSheet?(e=>{let t=``;for(let n of e.cssRules)t+=n.cssText;return a(t)})(e):e,{is:c,defineProperty:l,getOwnPropertyDescriptor:u,getOwnPropertyNames:d,getOwnPropertySymbols:f,getPrototypeOf:p}=Object,m=globalThis,ee=m.trustedTypes,te=ee?ee.emptyScript:``,ne=m.reactiveElementPolyfillSupport,h=(e,t)=>e,re={toAttribute(e,t){switch(t){case Boolean:e=e?te:null;break;case Object:case Array:e=e==null?e:JSON.stringify(e)}return e},fromAttribute(e,t){let n=e;switch(t){case Boolean:n=e!==null;break;case Number:n=e===null?null:Number(e);break;case Object:case Array:try{n=JSON.parse(e)}catch{n=null}}return n}},ie=(e,t)=>!c(e,t),ae={attribute:!0,type:String,converter:re,reflect:!1,useDefault:!1,hasChanged:ie};Symbol.metadata??=Symbol(`metadata`),m.litPropertyMetadata??=new WeakMap;var g=class extends HTMLElement{static addInitializer(e){this._$Ei(),(this.l??=[]).push(e)}static get observedAttributes(){return this.finalize(),this._$Eh&&[...this._$Eh.keys()]}static createProperty(e,t=ae){if(t.state&&(t.attribute=!1),this._$Ei(),this.prototype.hasOwnProperty(e)&&((t=Object.create(t)).wrapped=!0),this.elementProperties.set(e,t),!t.noAccessor){let n=Symbol(),r=this.getPropertyDescriptor(e,n,t);r!==void 0&&l(this.prototype,e,r)}}static getPropertyDescriptor(e,t,n){let{get:r,set:i}=u(this.prototype,e)??{get(){return this[t]},set(e){this[t]=e}};return{get:r,set(t){let a=r?.call(this);i?.call(this,t),this.requestUpdate(e,a,n)},configurable:!0,enumerable:!0}}static getPropertyOptions(e){return this.elementProperties.get(e)??ae}static _$Ei(){if(this.hasOwnProperty(h(`elementProperties`)))return;let e=p(this);e.finalize(),e.l!==void 0&&(this.l=[...e.l]),this.elementProperties=new Map(e.elementProperties)}static finalize(){if(this.hasOwnProperty(h(`finalized`)))return;if(this.finalized=!0,this._$Ei(),this.hasOwnProperty(h(`properties`))){let e=this.properties,t=[...d(e),...f(e)];for(let n of t)this.createProperty(n,e[n])}let e=this[Symbol.metadata];if(e!==null){let t=litPropertyMetadata.get(e);if(t!==void 0)for(let[e,n]of t)this.elementProperties.set(e,n)}this._$Eh=new Map;for(let[e,t]of this.elementProperties){let n=this._$Eu(e,t);n!==void 0&&this._$Eh.set(n,e)}this.elementStyles=this.finalizeStyles(this.styles)}static finalizeStyles(e){let t=[];if(Array.isArray(e)){let n=new Set(e.flat(1/0).reverse());for(let e of n)t.unshift(s(e))}else e!==void 0&&t.push(s(e));return t}static _$Eu(e,t){let n=t.attribute;return!1===n?void 0:typeof n==`string`?n:typeof e==`string`?e.toLowerCase():void 0}constructor(){super(),this._$Ep=void 0,this.isUpdatePending=!1,this.hasUpdated=!1,this._$Em=null,this._$Ev()}_$Ev(){this._$ES=new Promise(e=>this.enableUpdating=e),this._$AL=new Map,this._$E_(),this.requestUpdate(),this.constructor.l?.forEach(e=>e(this))}addController(e){(this._$EO??=new Set).add(e),this.renderRoot!==void 0&&this.isConnected&&e.hostConnected?.()}removeController(e){this._$EO?.delete(e)}_$E_(){let e=new Map,t=this.constructor.elementProperties;for(let n of t.keys())this.hasOwnProperty(n)&&(e.set(n,this[n]),delete this[n]);e.size>0&&(this._$Ep=e)}createRenderRoot(){let e=this.shadowRoot??this.attachShadow(this.constructor.shadowRootOptions);return o(e,this.constructor.elementStyles),e}connectedCallback(){this.renderRoot??=this.createRenderRoot(),this.enableUpdating(!0),this._$EO?.forEach(e=>e.hostConnected?.())}enableUpdating(e){}disconnectedCallback(){this._$EO?.forEach(e=>e.hostDisconnected?.())}attributeChangedCallback(e,t,n){this._$AK(e,n)}_$ET(e,t){let n=this.constructor.elementProperties.get(e),r=this.constructor._$Eu(e,n);if(r!==void 0&&!0===n.reflect){let i=(n.converter?.toAttribute===void 0?re:n.converter).toAttribute(t,n.type);this._$Em=e,i==null?this.removeAttribute(r):this.setAttribute(r,i),this._$Em=null}}_$AK(e,t){let n=this.constructor,r=n._$Eh.get(e);if(r!==void 0&&this._$Em!==r){let e=n.getPropertyOptions(r),i=typeof e.converter==`function`?{fromAttribute:e.converter}:e.converter?.fromAttribute===void 0?re:e.converter;this._$Em=r;let a=i.fromAttribute(t,e.type);this[r]=a??this._$Ej?.get(r)??a,this._$Em=null}}requestUpdate(e,t,n,r=!1,i){if(e!==void 0){let a=this.constructor;if(!1===r&&(i=this[e]),n??=a.getPropertyOptions(e),!((n.hasChanged??ie)(i,t)||n.useDefault&&n.reflect&&i===this._$Ej?.get(e)&&!this.hasAttribute(a._$Eu(e,n))))return;this.C(e,t,n)}!1===this.isUpdatePending&&(this._$ES=this._$EP())}C(e,t,{useDefault:n,reflect:r,wrapped:i},a){n&&!(this._$Ej??=new Map).has(e)&&(this._$Ej.set(e,a??t??this[e]),!0!==i||a!==void 0)||(this._$AL.has(e)||(this.hasUpdated||n||(t=void 0),this._$AL.set(e,t)),!0===r&&this._$Em!==e&&(this._$Eq??=new Set).add(e))}async _$EP(){this.isUpdatePending=!0;try{await this._$ES}catch(e){Promise.reject(e)}let e=this.scheduleUpdate();return e!=null&&await e,!this.isUpdatePending}scheduleUpdate(){return this.performUpdate()}performUpdate(){if(!this.isUpdatePending)return;if(!this.hasUpdated){if(this.renderRoot??=this.createRenderRoot(),this._$Ep){for(let[e,t]of this._$Ep)this[e]=t;this._$Ep=void 0}let e=this.constructor.elementProperties;if(e.size>0)for(let[t,n]of e){let{wrapped:e}=n,r=this[t];!0!==e||this._$AL.has(t)||r===void 0||this.C(t,void 0,n,r)}}let e=!1,t=this._$AL;try{e=this.shouldUpdate(t),e?(this.willUpdate(t),this._$EO?.forEach(e=>e.hostUpdate?.()),this.update(t)):this._$EM()}catch(t){throw e=!1,this._$EM(),t}e&&this._$AE(t)}willUpdate(e){}_$AE(e){this._$EO?.forEach(e=>e.hostUpdated?.()),this.hasUpdated||(this.hasUpdated=!0,this.firstUpdated(e)),this.updated(e)}_$EM(){this._$AL=new Map,this.isUpdatePending=!1}get updateComplete(){return this.getUpdateComplete()}getUpdateComplete(){return this._$ES}shouldUpdate(e){return!0}update(e){this._$Eq&&=this._$Eq.forEach(e=>this._$ET(e,this[e])),this._$EM()}updated(e){}firstUpdated(e){}};g.elementStyles=[],g.shadowRootOptions={mode:`open`},g[h(`elementProperties`)]=new Map,g[h(`finalized`)]=new Map,ne?.({ReactiveElement:g}),(m.reactiveElementVersions??=[]).push(`2.1.2`);var _=globalThis,oe=e=>e,v=_.trustedTypes,se=v?v.createPolicy(`lit-html`,{createHTML:e=>e}):void 0,ce=`$lit$`,y=`lit$${Math.random().toFixed(9).slice(2)}$`,le=`?`+y,ue=`<${le}>`,b=document,x=()=>b.createComment(``),S=e=>e===null||typeof e!=`object`&&typeof e!=`function`,C=Array.isArray,de=e=>C(e)||typeof e?.[Symbol.iterator]==`function`,w=`[ 	
\f\r]`,T=/<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g,fe=/-->/g,pe=/>/g,E=RegExp(`>|${w}(?:([^\\s"'>=/]+)(${w}*=${w}*(?:[^ \t\n\f\r"'\`<>=]|("|')|))|$)`,`g`),me=/'/g,he=/"/g,ge=/^(?:script|style|textarea|title)$/i,D=(e=>(t,...n)=>({_$litType$:e,strings:t,values:n}))(1),O=Symbol.for(`lit-noChange`),k=Symbol.for(`lit-nothing`),_e=new WeakMap,A=b.createTreeWalker(b,129);function ve(e,t){if(!C(e)||!e.hasOwnProperty(`raw`))throw Error(`invalid template strings array`);return se===void 0?t:se.createHTML(t)}var ye=(e,t)=>{let n=e.length-1,r=[],i,a=t===2?`<svg>`:t===3?`<math>`:``,o=T;for(let t=0;t<n;t++){let n=e[t],s,c,l=-1,u=0;for(;u<n.length&&(o.lastIndex=u,c=o.exec(n),c!==null);)u=o.lastIndex,o===T?c[1]===`!--`?o=fe:c[1]===void 0?c[2]===void 0?c[3]!==void 0&&(o=E):(ge.test(c[2])&&(i=RegExp(`</`+c[2],`g`)),o=E):o=pe:o===E?c[0]===`>`?(o=i??T,l=-1):c[1]===void 0?l=-2:(l=o.lastIndex-c[2].length,s=c[1],o=c[3]===void 0?E:c[3]===`"`?he:me):o===he||o===me?o=E:o===fe||o===pe?o=T:(o=E,i=void 0);let d=o===E&&e[t+1].startsWith(`/>`)?` `:``;a+=o===T?n+ue:l>=0?(r.push(s),n.slice(0,l)+ce+n.slice(l)+y+d):n+y+(l===-2?t:d)}return[ve(e,a+(e[n]||`<?>`)+(t===2?`</svg>`:t===3?`</math>`:``)),r]},be=class e{constructor({strings:t,_$litType$:n},r){let i;this.parts=[];let a=0,o=0,s=t.length-1,c=this.parts,[l,u]=ye(t,n);if(this.el=e.createElement(l,r),A.currentNode=this.el.content,n===2||n===3){let e=this.el.content.firstChild;e.replaceWith(...e.childNodes)}for(;(i=A.nextNode())!==null&&c.length<s;){if(i.nodeType===1){if(i.hasAttributes())for(let e of i.getAttributeNames())if(e.endsWith(ce)){let t=u[o++],n=i.getAttribute(e).split(y),r=/([.?@])?(.*)/.exec(t);c.push({type:1,index:a,name:r[2],strings:n,ctor:r[1]===`.`?Se:r[1]===`?`?Ce:r[1]===`@`?we:N}),i.removeAttribute(e)}else e.startsWith(y)&&(c.push({type:6,index:a}),i.removeAttribute(e));if(ge.test(i.tagName)){let e=i.textContent.split(y),t=e.length-1;if(t>0){i.textContent=v?v.emptyScript:``;for(let n=0;n<t;n++)i.append(e[n],x()),A.nextNode(),c.push({type:2,index:++a});i.append(e[t],x())}}}else if(i.nodeType===8){if(i.data===le)c.push({type:2,index:a});else{let e=-1;for(;(e=i.data.indexOf(y,e+1))!==-1;)c.push({type:7,index:a}),e+=y.length-1}}a++}}static createElement(e,t){let n=b.createElement(`template`);return n.innerHTML=e,n}};function j(e,t,n=e,r){if(t===O)return t;let i=r===void 0?n._$Cl:n._$Co?.[r],a=S(t)?void 0:t._$litDirective$;return i?.constructor!==a&&(i?._$AO?.(!1),a===void 0?i=void 0:(i=new a(e),i._$AT(e,n,r)),r===void 0?n._$Cl=i:(n._$Co??=[])[r]=i),i!==void 0&&(t=j(e,i._$AS(e,t.values),i,r)),t}var xe=class{constructor(e,t){this._$AV=[],this._$AN=void 0,this._$AD=e,this._$AM=t}get parentNode(){return this._$AM.parentNode}get _$AU(){return this._$AM._$AU}u(e){let{el:{content:t},parts:n}=this._$AD,r=(e?.creationScope??b).importNode(t,!0);A.currentNode=r;let i=A.nextNode(),a=0,o=0,s=n[0];for(;s!==void 0;){if(a===s.index){let t;s.type===2?t=new M(i,i.nextSibling,this,e):s.type===1?t=new s.ctor(i,s.name,s.strings,this,e):s.type===6&&(t=new Te(i,this,e)),this._$AV.push(t),s=n[++o]}a!==s?.index&&(i=A.nextNode(),a++)}return A.currentNode=b,r}p(e){let t=0;for(let n of this._$AV)n!==void 0&&(n.strings===void 0?n._$AI(e[t]):(n._$AI(e,n,t),t+=n.strings.length-2)),t++}},M=class e{get _$AU(){return this._$AM?._$AU??this._$Cv}constructor(e,t,n,r){this.type=2,this._$AH=k,this._$AN=void 0,this._$AA=e,this._$AB=t,this._$AM=n,this.options=r,this._$Cv=r?.isConnected??!0}get parentNode(){let e=this._$AA.parentNode,t=this._$AM;return t!==void 0&&e?.nodeType===11&&(e=t.parentNode),e}get startNode(){return this._$AA}get endNode(){return this._$AB}_$AI(e,t=this){e=j(this,e,t),S(e)?e===k||e==null||e===``?(this._$AH!==k&&this._$AR(),this._$AH=k):e!==this._$AH&&e!==O&&this._(e):e._$litType$===void 0?e.nodeType===void 0?de(e)?this.k(e):this._(e):this.T(e):this.$(e)}O(e){return this._$AA.parentNode.insertBefore(e,this._$AB)}T(e){this._$AH!==e&&(this._$AR(),this._$AH=this.O(e))}_(e){this._$AH!==k&&S(this._$AH)?this._$AA.nextSibling.data=e:this.T(b.createTextNode(e)),this._$AH=e}$(e){let{values:t,_$litType$:n}=e,r=typeof n==`number`?this._$AC(e):(n.el===void 0&&(n.el=be.createElement(ve(n.h,n.h[0]),this.options)),n);if(this._$AH?._$AD===r)this._$AH.p(t);else{let e=new xe(r,this),n=e.u(this.options);e.p(t),this.T(n),this._$AH=e}}_$AC(e){let t=_e.get(e.strings);return t===void 0&&_e.set(e.strings,t=new be(e)),t}k(t){C(this._$AH)||(this._$AH=[],this._$AR());let n=this._$AH,r,i=0;for(let a of t)i===n.length?n.push(r=new e(this.O(x()),this.O(x()),this,this.options)):r=n[i],r._$AI(a),i++;i<n.length&&(this._$AR(r&&r._$AB.nextSibling,i),n.length=i)}_$AR(e=this._$AA.nextSibling,t){for(this._$AP?.(!1,!0,t);e!==this._$AB;){let t=oe(e).nextSibling;oe(e).remove(),e=t}}setConnected(e){this._$AM===void 0&&(this._$Cv=e,this._$AP?.(e))}},N=class{get tagName(){return this.element.tagName}get _$AU(){return this._$AM._$AU}constructor(e,t,n,r,i){this.type=1,this._$AH=k,this._$AN=void 0,this.element=e,this.name=t,this._$AM=r,this.options=i,n.length>2||n[0]!==``||n[1]!==``?(this._$AH=Array(n.length-1).fill(new String),this.strings=n):this._$AH=k}_$AI(e,t=this,n,r){let i=this.strings,a=!1;if(i===void 0)e=j(this,e,t,0),a=!S(e)||e!==this._$AH&&e!==O,a&&(this._$AH=e);else{let r=e,o,s;for(e=i[0],o=0;o<i.length-1;o++)s=j(this,r[n+o],t,o),s===O&&(s=this._$AH[o]),a||=!S(s)||s!==this._$AH[o],s===k?e=k:e!==k&&(e+=(s??``)+i[o+1]),this._$AH[o]=s}a&&!r&&this.j(e)}j(e){e===k?this.element.removeAttribute(this.name):this.element.setAttribute(this.name,e??``)}},Se=class extends N{constructor(){super(...arguments),this.type=3}j(e){this.element[this.name]=e===k?void 0:e}},Ce=class extends N{constructor(){super(...arguments),this.type=4}j(e){this.element.toggleAttribute(this.name,!!e&&e!==k)}},we=class extends N{constructor(e,t,n,r,i){super(e,t,n,r,i),this.type=5}_$AI(e,t=this){if((e=j(this,e,t,0)??k)===O)return;let n=this._$AH,r=e===k&&n!==k||e.capture!==n.capture||e.once!==n.once||e.passive!==n.passive,i=e!==k&&(n===k||r);r&&this.element.removeEventListener(this.name,this,n),i&&this.element.addEventListener(this.name,this,e),this._$AH=e}handleEvent(e){typeof this._$AH==`function`?this._$AH.call(this.options?.host??this.element,e):this._$AH.handleEvent(e)}},Te=class{constructor(e,t,n){this.element=e,this.type=6,this._$AN=void 0,this._$AM=t,this.options=n}get _$AU(){return this._$AM._$AU}_$AI(e){j(this,e)}},Ee={M:ce,P:y,A:le,C:1,L:ye,R:xe,D:de,V:j,I:M,H:N,N:Ce,U:we,B:Se,F:Te},De=_.litHtmlPolyfillSupport;De?.(be,M),(_.litHtmlVersions??=[]).push(`3.3.3`);var Oe=(e,t,n)=>{let r=n?.renderBefore??t,i=r._$litPart$;if(i===void 0){let e=n?.renderBefore??null;r._$litPart$=i=new M(t.insertBefore(x(),e),e,void 0,n??{})}return i._$AI(e),i},P=globalThis,F=class extends g{constructor(){super(...arguments),this.renderOptions={host:this},this._$Do=void 0}createRenderRoot(){let e=super.createRenderRoot();return this.renderOptions.renderBefore??=e.firstChild,e}update(e){let t=this.render();this.hasUpdated||(this.renderOptions.isConnected=this.isConnected),super.update(e),this._$Do=Oe(t,this.renderRoot,this.renderOptions)}connectedCallback(){super.connectedCallback(),this._$Do?.setConnected(!0)}disconnectedCallback(){super.disconnectedCallback(),this._$Do?.setConnected(!1)}render(){return O}};F._$litElement$=!0,F.finalized=!0,P.litElementHydrateSupport?.({LitElement:F});var ke=P.litElementPolyfillSupport;ke?.({LitElement:F}),(P.litElementVersions??=[]).push(`4.2.2`);var Ae=class extends F{createRenderRoot(){return this}render(){return D`
      <div class="backdrop" aria-hidden="true">
        <span class="orb orb--indigo"></span>
        <span class="orb orb--violet"></span>
        <span class="orb orb--teal"></span>
        <span class="grain"></span>
      </div>
    `}};customElements.define(`app-backdrop`,Ae);var je=1e3,Me=8e3,Ne=4600,Pe=5e3,Fe={read:D`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4M10 12h5M10 16h5"/></svg>`,edit:D`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20l4-1 10-10-3-3L5 16z"/><path d="M14 6l3 3M4 20l1-4"/></svg>`,execute:D`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M5 6l6 6-6 6M13 18h6"/></svg>`,search:D`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/></svg>`,think:D`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18h6M10 21h4M12 3a6 6 0 0 1 3.5 10.9c-.4.3-.5.7-.5 1.1H9c0-.4-.1-.8-.5-1.1A6 6 0 0 1 12 3z"/></svg>`,fetch:D`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12M7 10l5 5 5-5M5 21h14"/></svg>`,other:D`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M12 12l8-4.5M12 12l-8-4.5M12 12v9"/></svg>`},Ie=D`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l7 3v6c0 4-3 7-7 9-4-2-7-5-7-9V6z"/><path d="M9 12l2 2 4-4"/></svg>`,Le=D`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>`,Re=D`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1"/><circle cx="12" cy="12" r="3.2"/></svg>`,ze=D`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5M6 11l6-6 6 6"/></svg>`,Be=D`<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="7" y="7" width="10" height="10" rx="2"/></svg>`,Ve=D`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 4h14v16H5z"/><path d="M8 9h8M8 13h8M8 17h5"/></svg>`,He=D`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>`,Ue=D`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 11a8 8 0 1 0-2.3 6.7"/><path d="M20 4v7h-7"/></svg>`;function We(){return{status:`starting`,busy:!1,busy_message:``,connected:!1,had_connection:!1,disconnect_notified:!1,stopping:!1,workspace:``,session_id:null,config_options:[],modes:{},agent:{name:`cecli`,version:``},turn_state:`idle`,usage:{used:0,size:0,cost:null},auto_scroll:!0,last_prompt:``,retry_available:!1,draft:``,draft_revision:0,transcript:[],permissions:[],logs:[],toasts:[],turn_sequence:0,current_assistant_id:null,new_chat_pending:!1,restart_pending:!1}}var Ge=class{constructor(e){this._state=e,this._listeners=new Set}get state(){return this._state}subscribe(e){return this._listeners.add(e),()=>this._listeners.delete(e)}update(e){let t=e(this._state);t&&t!==this._state&&(this._state=t,this.emit())}emit(){for(let e of this._listeners)e(this._state)}},I=class{constructor(e,t){this.host=e,this.store=t,this._unsubscribe=null,e.addController(this)}get state(){return this.store.state}hostConnected(){this._unsubscribe=this.store.subscribe(()=>this.host.requestUpdate())}hostDisconnected(){this._unsubscribe&&this._unsubscribe(),this._unsubscribe=null}},L={connection_label(e){let t=e.status||`starting`;return t===`ready`&&e.busy&&(t=`busy`),!e.connected&&e.had_connection&&(t=`reconnecting`),t},turn_label(e){return(e.turn_state||`idle`).replace(/_/g,` `)},busy_text(e){return e.busy_message||`cecli is working…`},retry_visible(e){return!(!e.retry_available||!e.last_prompt||e.busy||e.stopping)},usage_percent(e){let{used:t,size:n}=e.usage;return n>0?Math.min(Math.max(t/n*100,0),100):0},usage_level(e){let t=L.usage_percent(e);return t>90?`high`:t>70?`warn`:`normal`},has_transcript(e){return e.transcript.length>0}},R=new Ge(We()),Ke=class extends F{constructor(){super(),this._store=new I(this,R)}createRenderRoot(){return this}render(){let e=this._store.state,t=L.connection_label(e);return D`
      <header class="topbar">
        <div class="brand">
          <span class="brand-mark" aria-hidden="true">${Re}</span>
          <span class="brand-name">cecli</span>
        </div>

        <div class="workspace" title=${e.workspace||``}>
          <span class="workspace-path">${e.workspace||`—`}</span>
        </div>

        <span
          class="connection-status"
          data-status=${t}
          role="status"
          aria-label=${`Connection status: ${t}`}
        >
          <span class="status-dot" aria-hidden="true"></span>
          <span class="status-label">${t}</span>
        </span>
      </header>
    `}};customElements.define(`app-header`,Ke);async function z(e,t){let n;try{n=await fetch(e,{method:`POST`,headers:{"Content-Type":`application/json`},body:JSON.stringify(t===void 0?{}:t)})}catch(e){throw Error(`Network error: ${e.message}`)}let r=null;try{r=await n.json()}catch{r=null}if(!n.ok){let e=r&&(r.error||r.message)?r.error||r.message:`Request failed (${n.status})`;throw Error(e)}return r}async function qe(){let e=await fetch(`/api/state`,{headers:{Accept:`application/json`}});if(!e.ok)throw Error(`state request failed (${e.status})`);return e.json()}function Je(e){let t=Number(e);if(!Number.isFinite(t)||t<0)return`—`;if(t<1e3)return String(Math.round(t));if(t<1e6){let e=t/1e3;return`${e>=100?Math.round(e):Xe(e.toFixed(1))}k`}return`${Xe((t/1e6).toFixed(1))}m`}function Ye(e){if(!e||typeof e.amount!=`number`)return``;let t=typeof e.currency==`string`?e.currency.toUpperCase():``;try{return new Intl.NumberFormat(void 0,{style:`currency`,currency:t,maximumFractionDigits:4}).format(e.amount)}catch{return`${t} ${e.amount.toFixed(4)}`.trim()}}function Xe(e){return String(e).replace(/\.0$/,``)}function Ze(e){return typeof e.sessionUpdate==`string`?e.sessionUpdate:typeof e.type==`string`?e.type:e.toolCallId&&typeof e.status==`string`?`tool_call_update`:e.toolCallId?`tool_call`:``}function B(e){if(!e)return``;if(typeof e==`string`)return e;if(Array.isArray(e))return e.map(B).filter(Boolean).join(`
`);if(typeof e==`object`){if(typeof e.text==`string`)return e.text;if(e.content)return B(e.content)}return``}function Qe(e){let t=typeof e==`string`?e:String(e||``),n=t.trim(),r=/^```[^\n]*\n([\s\S]*?)\n?```$/.exec(n);return r?r[1]:t}function $e(e){return Qe(e).replace(/\n{3,}/g,`

`).trimEnd()}function et(e){let t=String(e||``).toLowerCase();return t===`read`||t===`delete`||t===`move`?`read`:t===`edit`?`edit`:t===`execute`?`execute`:t===`search`?`search`:t===`think`?`think`:t===`fetch`?`fetch`:`other`}function tt(e){let t={read:`Reading files`,edit:`Editing files`,execute:`Running command`,search:`Searching`,think:`Thinking`,fetch:`Fetching`,other:`Tool call`};return t[e]||t.other}function nt(e){return e===`in_progress`?`In progress`:e===`completed`?`Completed`:e===`failed`?`Failed`:`Pending`}function rt(e){let t=String(e||``);return t.startsWith(`allow`)?`perm-option--allow`:t.startsWith(`reject`)?`perm-option--reject`:``}function it(e){let t=String(e||``).split(/[\\/]/);return t[t.length-1]||String(e||``)}function at(e){return e?typeof e.line==`number`?e.line:e.line&&typeof e.line.start==`number`?e.line.start:null:null}function ot(e){if(!e||!e.path)return``;let t=at(e);return t?`${it(e.path)}:${t}`:it(e.path)}var st=0;function V(e,t,n=`info`){let r=typeof t==`string`?t:String(t),i=`[${new Date().toLocaleTimeString([],{hour12:!1})}] ${String(n||`info`).padEnd(5)} ${r}`;e.update(e=>{let t=[...e.logs,i];return{...e,logs:t.length>200?t.slice(-200):t}})}function H(e,t,n=`info`){st+=1;let r=st;e.update(e=>({...e,toasts:[...e.toasts,{id:r,message:String(t),kind:n||`info`,visible:!1}]})),requestAnimationFrame(()=>{e.update(e=>({...e,toasts:e.toasts.map(e=>e.id===r?{...e,visible:!0}:e)}))}),setTimeout(()=>{e.update(e=>({...e,toasts:e.toasts.map(e=>e.id===r?{...e,visible:!1}:e)})),setTimeout(()=>{e.update(e=>({...e,toasts:e.toasts.filter(e=>e.id!==r)}))},260)},Ne)}function ct(e,t){return{...e,transcript:[...e.transcript,{id:q(`user`),type:`user`,text:t}]}}function lt(e){return{...U(e),current_assistant_id:null,turn_sequence:e.turn_sequence+1}}function ut(e,t){if(!t)return e;let n=W(e),r=wt({...n.assistant,had_text:!0}),i=r.parts[r.parts.length-1];return r=i&&i.type===`text`?{...r,parts:r.parts.map(e=>e.id===i.id?{...e,text:e.text+t,streaming:!0}:e)}:{...r,parts:[...K(r.parts),{id:q(`text`),type:`text`,text:t,streaming:!0}]},G(n.state,r)}function dt(e,t){if(!t)return e;let n=W(e),r=n.assistant.parts.find(e=>e.type===`thought`),i;if(r)i={...n.assistant,parts:n.assistant.parts.map(e=>e.id===r.id?{...e,text:e.text+t}:e)};else{let e=!n.assistant.had_text;i={...n.assistant,parts:[...n.assistant.parts,{id:q(`thought`),type:`thought`,text:t,open:e,auto_open:e}]}}return G(n.state,i)}function ft(e,t,n){let r=String(t?.toolCallId),i=W(e),a=i.assistant.parts.find(e=>e.type===`tool`&&e.tool_id===r);if(a)return G(i.state,{...i.assistant,parts:i.assistant.parts.map(e=>e.id===a.id?Et(e,t):e)});let o=n?K(i.assistant.parts):i.assistant.parts,s=Et(Tt(r),t);return G(i.state,{...i.assistant,parts:[...o,s]})}function pt(e,t){let n=String(t?.toolCallId),r=W(e),i=r.assistant.parts.find(e=>e.type===`tool`&&e.tool_id===n),a=B(t?.content);if(i)return G(r.state,{...r.assistant,parts:r.assistant.parts.map(e=>e.id===i.id?{...e,content_text:e.content_text+a}:e)});let o={...Tt(n),content_text:a};return G(r.state,{...r.assistant,parts:[...r.assistant.parts,o]})}function mt(e,t){let n=W(e),r=Array.isArray(t)?t.map(e=>({content:e?.content||``,status:e?.status||`pending`})):[],i=n.assistant.parts.find(e=>e.type===`plan`);return i?G(n.state,{...n.assistant,parts:n.assistant.parts.map(e=>e.id===i.id?{...e,entries:r}:e)}):G(n.state,{...n.assistant,parts:[...K(n.assistant.parts),{id:q(`plan`),type:`plan`,entries:r}]})}function ht(e,t,n){let r=Ct(e);if(!r)return e;let i=r.parts.find(e=>e.id===t);return!i||i.open===n?e:G(e,{...r,parts:r.parts.map(e=>e.id===t?{...e,open:n}:e)})}function U(e){let t=Ct(e);return t?{...G(e,{...t,parts:K(t.parts)}),current_assistant_id:null}:e}function gt(e,t=!0){return{...e,transcript:[],permissions:[],current_assistant_id:null,turn_sequence:0,auto_scroll:!0,usage:t?{used:0,size:0,cost:null}:e.usage}}function _t(e,t){let n=String(t?.requestId);if(e.permissions.some(e=>e.key===n))return e;let r=t?.toolCall||{},i=B(r.content).trim();return{...e,permissions:[...e.permissions,{key:n,request_id:t?.requestId,tool_call:r,options:Array.isArray(t?.options)?t.options:[],detail:i,resolved:!1,resolving:!1,chosen:null,status_kind:``,status_text:``}]}}function vt(e,t,n){let r=e.permissions.find(e=>e.key===t);return!r||r.resolving===n?e:{...e,permissions:e.permissions.map(e=>e.key===t?{...e,resolving:n}:e)}}function yt(e,t,n){let r=e.permissions.find(e=>e.key===t);if(!r||r.resolved)return e;let i=n==null?null:String(n),a=r.options.find(e=>String(e.optionId)===i)||null;return{...e,permissions:e.permissions.map(e=>e.key===t?{...e,resolved:!0,resolving:!1,chosen:i,status_kind:a?String(a.kind||``):`dismissed`,status_text:i===null?`Dismissed`:a?a.name:`Selected`}:e)}}function bt(e,t){return e.permissions.some(e=>e.key===t)?{...e,permissions:e.permissions.filter(e=>e.key!==t)}:e}function xt(e){return e.permissions.length?{...e,permissions:[]}:e}function St(e){return e.permissions.some(e=>!e.resolved)}function W(e){let t=Ct(e);if(t)return{state:e,assistant:t};let n={id:q(`turn`),type:`assistant`,turn:e.turn_sequence,parts:[],had_text:!1};return{state:{...e,transcript:[...e.transcript,n],current_assistant_id:n.id},assistant:n}}function Ct(e){return e.current_assistant_id&&e.transcript.find(t=>t.id===e.current_assistant_id)||null}function G(e,t){return{...e,transcript:e.transcript.map(e=>e.id===t.id?t:e)}}function wt(e){let t=e.parts.find(e=>e.type===`thought`);if(!t)return e;let n=t.auto_open&&t.open?!1:t.open;return{...e,parts:e.parts.map(e=>e.id===t.id?{...e,open:n,auto_open:!1}:e)}}function K(e){return e.map(e=>e.type===`text`&&e.streaming?{...e,streaming:!1}:e)}function Tt(e){return{id:q(`tool`),type:`tool`,tool_id:e,kind:`other`,title:`Tool call`,status:`pending`,locations:[],content_text:``}}function Et(e,t){let n={...e};if(t.kind&&(n.kind=et(t.kind)),t.title?n.title=t.title:n.title&&n.title!==`Tool call`||(n.title=tt(n.kind)),t.status&&(n.status=t.status),Array.isArray(t.locations)&&(n.locations=t.locations),t.content!==void 0){let e=B(t.content);e&&(n.content_text=e)}return n}function q(e){return`${e}-${globalThis.crypto?.randomUUID?.()||`${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`}`}function Dt(e,t,n={}){if(t&&typeof t==`object`)switch(t.type){case`status`:kt(e,t);break;case`session`:At(e,t);break;case`update`:if(!Ht(e,t))break;jt(e,t.update||{});break;case`permission`:if(!Ut(e,t))break;e.update(e=>Ot(e,t));break;case`permission_resolved`:Pt(e,t,n);break;case`prompt_done`:Nt(e,t,n);break;case`log`:V(e,t.message,t.level||`info`);break;case`error`:Ft(e,t)}}function Ot(e,t){let n=_t(e,t);return n===e?e:{...n,busy:!0,turn_state:`requires_action`,busy_message:`Waiting for your approval`}}function kt(e,t){t.agent&&e.update(e=>Rt(e,t.agent)),t.detail&&V(e,String(t.detail),`info`),t.status===`exited`&&(e.update(e=>({...xt(U(e)),busy:!1,stopping:!1,busy_message:``,turn_state:`idle`,retry_available:!!e.last_prompt})),H(e,`cecli exited`,`error`)),Lt(e,t.status)}function At(e,t){It(e,t.sessionId),t.modes&&e.update(e=>({...e,modes:t.modes})),Array.isArray(t.configOptions)&&J(e,t.configOptions)}function jt(e,t){if(t&&typeof t==`object`)switch(Ze(t)){case`agent_message_chunk`:e.update(e=>ut(e,B(t.content)));break;case`agent_thought_chunk`:e.update(e=>dt(e,B(t.content)));break;case`tool_call`:e.update(e=>ft(e,t,!0));break;case`tool_call_update`:e.update(e=>ft(e,t,!1));break;case`tool_call_content_chunk`:e.update(e=>pt(e,t));break;case`plan`:e.update(e=>mt(e,t.entries));break;case`usage_update`:e.update(e=>Bt(e,t));break;case`config_option_update`:J(e,t.configOptions);break;case`current_mode_update`:e.update(e=>Vt(e,t.currentModeId));break;case`state_update`:Mt(e,t)}}function Mt(e,t){let n=t.state;n===`requires_action`?e.update(e=>({...e,busy:!0,turn_state:`requires_action`,busy_message:`Waiting for your approval`})):n===`running`?e.update(e=>({...e,busy:!0,turn_state:`running`,busy_message:`cecli is working…`})):n===`idle`&&e.update(e=>({...U(e),busy:!1,stopping:!1,turn_state:`idle`,busy_message:``}))}function Nt(e,t,n){e.update(e=>({...xt(U(e)),busy:!1,stopping:!1,turn_state:`idle`,busy_message:``,retry_available:t&&t.stopReason===`cancelled`?!!e.last_prompt:e.retry_available})),t&&t.stopReason===`cancelled`&&V(e,`turn cancelled`,`info`),typeof n.on_prompt_done==`function`&&n.on_prompt_done()}function Pt(e,t,n){let r=String(t.requestId);e.update(e=>Wt(yt(e,r,t.optionId))),typeof n.on_permission_resolved==`function`&&n.on_permission_resolved(r)}function Ft(e,t){let n=t.message||`Unknown bridge error`;e.update(e=>({...e,retry_available:!!e.last_prompt})),V(e,n,`error`),H(e,n,`error`)}function It(e,t){if(!t)return;let n=!1;e.update(e=>e.session_id&&e.session_id!==t?(n=!0,{...gt(e,!1),session_id:t}):e.session_id===t?e:{...e,session_id:t}),n&&H(e,`Session restarted`,`info`)}function Lt(e,t){e.update(e=>{let n=t||e.status,r=n===`exited`;return e.status===n&&(!r||!e.busy)?e:{...e,status:n,busy:!r&&e.busy,stopping:!r&&e.stopping,busy_message:r?``:e.busy_message}})}function Rt(e,t){if(!t)return e;let n=t.name||e.agent.name,r=t.version||``;return e.agent.name===n&&e.agent.version===r?e:{...e,agent:{name:n,version:r}}}function zt(e,t){return typeof t!=`string`||!t||e.workspace===t?e:{...e,workspace:t}}function Bt(e,t){let n=Number(t.used),r=Number(t.size),i={...e.usage};return Number.isFinite(n)&&(i.used=n),Number.isFinite(r)&&(i.size=r),t.cost&&(i.cost=t.cost),i.used===e.usage.used&&i.size===e.usage.size&&i.cost===e.usage.cost?e:{...e,usage:i}}function J(e,t){Array.isArray(t)&&e.update(e=>e.config_options===t?e:{...e,config_options:t})}function Vt(e,t){if(t==null)return e;let n=String(t),r=!1,i=e.config_options.map(e=>e.id!==`mode`||String(e.currentValue)===n?e:(r=!0,{...e,currentValue:t}));return r?{...e,config_options:i}:e}function Ht(e,t){let n=e.state.session_id;return n?!t.sessionId||t.sessionId===n:!1}function Ut(e,t){let n=e.state.session_id;return!n||!t.sessionId||t.sessionId===n}function Wt(e){if(St(e))return e;let t=e.busy?`running`:`idle`,n=e.busy?`cecli is working…`:``;return e.turn_state===t&&e.busy_message===n?e:{...e,turn_state:t,busy_message:n}}function Gt(e,t){if(t&&typeof t==`object`){if(e.update(e=>zt(e,t.workspace)),t.agent&&e.update(e=>Rt(e,t.agent)),t.modes&&e.update(e=>({...e,modes:t.modes})),Array.isArray(t.configOptions)&&J(e,t.configOptions),It(e,t.sessionId),typeof t.busy==`boolean`&&e.update(e=>{if(t.busy){let t=St(e),n=`running`,r=`cecli is working…`;return e.stopping?r=`Stopping…`:t&&(n=`requires_action`,r=`Waiting for your approval`),{...e,busy:!0,stopping:e.stopping,turn_state:n,busy_message:r}}return{...U(e),busy:!1,stopping:!1,turn_state:`idle`,busy_message:``}}),t.usage&&e.update(e=>Bt(e,t.usage)),Array.isArray(t.permissions)){let n=new Set(t.permissions.map(e=>String(e.requestId)));e.update(e=>{let t=e.permissions.filter(e=>n.has(e.key));return t.length===e.permissions.length?e:{...e,permissions:t}});for(let n of t.permissions)e.update(e=>_t(e,n));t.permissions.length&&e.update(e=>St(e)?{...e,busy:!0,turn_state:`requires_action`,busy_message:`Waiting for your approval`}:e)}Lt(e,t.status),e.update(e=>e.stopping?e:Wt(e))}}var Y=new class{constructor(e){this.store=e,this.event_source=null,this.reconnect_timer=null,this.reconnect_delay=je,this.permission_timers=new Map}start(){this.connect()}connect(){clearTimeout(this.reconnect_timer),this.reconnect_timer=null,this.event_source&&this.event_source.close();let e=new EventSource(`/api/events`);this.event_source=e,e.onopen=()=>{this.reconnect_delay=je,this.store.update(e=>({...e,connected:!0,had_connection:!0,disconnect_notified:!1})),this.refresh_state()},e.onmessage=e=>{let t;try{t=JSON.parse(e.data)}catch{V(this.store,`malformed event: ${e.data}`,`error`);return}Dt(this.store,t,{on_permission_resolved:e=>this.schedule_permission_cleanup(e),on_prompt_done:()=>this.clear_permission_cleanup()})},e.onerror=()=>{this.event_source===e&&(e.close(),this.event_source=null,this.store.update(e=>({...e,connected:!1})),this.store.state.had_connection&&!this.store.state.disconnect_notified&&(this.store.update(e=>({...e,disconnect_notified:!0})),H(this.store,`Connection lost — reconnecting…`,`error`)),this.schedule_reconnect())}}schedule_reconnect(){if(this.reconnect_timer)return;let e=this.reconnect_delay;this.reconnect_timer=setTimeout(()=>{this.reconnect_timer=null,this.reconnect_delay=Math.min(this.reconnect_delay*2,Me),this.connect()},e)}async refresh_state(){try{Gt(this.store,await qe())}catch(e){V(this.store,`state sync failed: ${e.message}`,`error`)}}async send_prompt(e){let t=String(e||``).trim();if(!t||this.store.state.busy)return!1;if(this.store.state.status!==`ready`)return H(this.store,`cecli is not ready yet`,`error`),!1;try{return await z(`/api/prompt`,{text:t}),this.store.update(e=>({...lt(ct(e,t)),last_prompt:t,retry_available:!1,busy:!0,stopping:!1,busy_message:`cecli is working…`,turn_state:`running`})),!0}catch(e){return this.store.update(e=>({...e,last_prompt:t,retry_available:!0})),H(this.store,e.message,`error`),!1}}async cancel_turn(){let e=this.store.state;if(e.busy&&!e.stopping){this.store.update(e=>({...e,stopping:!0,busy_message:`Stopping…`}));try{await z(`/api/cancel`,{})}catch(e){this.store.update(e=>({...e,stopping:!1})),H(this.store,e.message,`error`)}}}async new_chat(){if(this.store.state.busy){H(this.store,`Finish or stop the current turn first`,`error`);return}this.clear_permission_cleanup(),this.store.update(e=>({...e,new_chat_pending:!0}));let e=this.store.state.workspace;try{await z(`/api/new_session`,e?{cwd:e}:{}),this.store.update(e=>({...gt(e),session_id:null,busy:!1,stopping:!1,busy_message:``,turn_state:`idle`})),H(this.store,`Started a new chat`,`info`),this.refresh_state()}catch(e){H(this.store,e.message,`error`)}finally{this.store.update(e=>({...e,new_chat_pending:!1}))}}async restart_server(){this.clear_permission_cleanup(),this.store.update(e=>({...e,restart_pending:!0}));try{await z(`/api/restart`,{}),this.store.update(e=>({...gt(e),session_id:null,busy:!1,stopping:!1,busy_message:``,status:`starting`,turn_state:`idle`})),H(this.store,`Restarting cecli…`,`info`)}catch(e){H(this.store,e.message,`error`)}finally{this.store.update(e=>({...e,restart_pending:!1}))}}async change_config(e,t){try{return await z(`/api/config`,{configId:e,value:t}),this.store.update(n=>({...n,config_options:n.config_options.map(n=>n.id===e?{...n,currentValue:t}:n)})),!0}catch(e){return H(this.store,e.message,`error`),!1}}async resolve_permission(e,t){let n=String(e),r=this.store.state.permissions.find(e=>e.key===n);if(!(!r||r.resolving||r.resolved)){this.store.update(e=>vt(e,n,!0));try{await z(`/api/permission`,{requestId:r.request_id,optionId:t}),this.store.update(e=>yt(e,n,t)),this.store.update(e=>Wt(e)),this.schedule_permission_cleanup(n)}catch(e){let t=this.store.state.permissions.find(e=>e.key===n);if(t&&t.resolved)return;this.store.update(e=>vt(e,n,!1)),H(this.store,e.message,`error`)}}}schedule_permission_cleanup(e){if(this.permission_timers.has(e))return;let t=setTimeout(()=>{this.permission_timers.delete(e),this.store.update(t=>bt(t,e))},Pe);this.permission_timers.set(e,t)}clear_permission_cleanup(){for(let e of this.permission_timers.values())clearTimeout(e);this.permission_timers.clear()}set_thought_open(e,t){this.store.update(n=>ht(n,e,t))}set_auto_scroll(e){let t=!!e;this.store.update(e=>e.auto_scroll===t?e:{...e,auto_scroll:t})}jump_to_latest(){this.set_auto_scroll(!0)}fill_composer(e){this.store.update(t=>({...t,draft:String(e||``),draft_revision:t.draft_revision+1}))}}(R),Kt=class extends F{constructor(){super(),this._store=new I(this,R),this._has_text=!1,this._sending=!1,this._applied_revision=0,this._on_global_keydown=this._on_global_keydown.bind(this)}createRenderRoot(){return this}connectedCallback(){super.connectedCallback(),document.addEventListener(`keydown`,this._on_global_keydown)}disconnectedCallback(){document.removeEventListener(`keydown`,this._on_global_keydown),super.disconnectedCallback()}updated(){let e=this._store.state;if(e.draft_revision===this._applied_revision)return;this._applied_revision=e.draft_revision;let t=this._textarea();t&&(t.value=e.draft,this._has_text=e.draft.trim().length>0,this._auto_grow(),t.focus())}render(){let e=this._store.state,t=e.busy,n=L.retry_visible(e),r=!t&&(this._sending||e.status!==`ready`||!this._has_text);return D`
      <footer class="composer">
        <div class="busy-indicator" ?hidden=${!t}>
          <span class="spinner" aria-hidden="true"></span>
          <span>${L.busy_text(e)}</span>
        </div>
        <div class="composer-box">
          <textarea
            id="composer-input"
            rows="1"
            placeholder="Ask cecli anything…"
            aria-label="Message cecli"
            autocomplete="off"
            spellcheck="true"
            @input=${this._on_input}
            @keydown=${this._on_keydown}
          ></textarea>
          <button
            class="send-btn"
            type="button"
            data-mode=${t?`stop`:`send`}
            aria-label=${t?`Stop this turn`:`Send message`}
            ?disabled=${r}
            @click=${this._on_send_click}
          >${t?Be:ze}</button>
        </div>
        <div class="composer-meta">
          <span class="hint">Enter to send · Shift+Enter for newline · Esc to stop</span>
          <div class="composer-state">
            <button
              class="retry-btn"
              type="button"
              ?hidden=${!n}
              @click=${this._retry}
            >Retry last</button>
            <span class="turn-status" data-state=${e.turn_state}>
              <span class="turn-dot" aria-hidden="true"></span>
              <span>${L.turn_label(e)}</span>
            </span>
          </div>
        </div>
      </footer>
    `}_textarea(){return this.querySelector(`#composer-input`)}_auto_grow(){let e=this._textarea();e&&(e.style.height=`auto`,e.style.height=`${Math.min(e.scrollHeight,180)}px`)}_on_input(){let e=this._textarea();e&&(this._has_text=e.value.trim().length>0,this._auto_grow(),this.requestUpdate())}_on_keydown(e){e.key!==`Enter`||e.shiftKey||e.isComposing||(e.preventDefault(),R.state.busy||this._submit())}_on_send_click(){R.state.busy?Y.cancel_turn():this._submit()}async _submit(){let e=this._textarea();if(!e||this._sending)return;let t=e.value.trim();if(!t||R.state.busy)return;this._sending=!0,this.requestUpdate();let n=!1;try{n=await Y.send_prompt(t)}finally{this._sending=!1}n&&(e.value=``,this._has_text=!1,this._auto_grow()),this.requestUpdate()}_retry(){let e=R.state;if(e.busy||!e.last_prompt)return;let t=this._textarea();t&&(t.value=e.last_prompt,this._has_text=!0,this._auto_grow(),this.requestUpdate(),this._submit())}_on_global_keydown(e){if(e.key!==`Escape`||!R.state.busy)return;let t=this._textarea();document.activeElement===t&&t.value.trim()||(e.preventDefault(),Y.cancel_turn())}};customElements.define(`composer-bar`,Kt);var qt={ATTRIBUTE:1,CHILD:2,PROPERTY:3,BOOLEAN_ATTRIBUTE:4,EVENT:5,ELEMENT:6},Jt=e=>(...t)=>({_$litDirective$:e,values:t}),Yt=class{constructor(e){}get _$AU(){return this._$AM._$AU}_$AT(e,t,n){this._$Ct=e,this._$AM=t,this._$Ci=n}_$AS(e,t){return this.update(e,t)}update(e,t){return this.render(...t)}},{I:Xt}=Ee,Zt=e=>e,Qt=()=>document.createComment(``),X=(e,t,n)=>{let r=e._$AA.parentNode,i=t===void 0?e._$AB:t._$AA;if(n===void 0)n=new Xt(r.insertBefore(Qt(),i),r.insertBefore(Qt(),i),e,e.options);else{let t=n._$AB.nextSibling,a=n._$AM,o=a!==e;if(o){let t;n._$AQ?.(e),n._$AM=e,n._$AP!==void 0&&(t=e._$AU)!==a._$AU&&n._$AP(t)}if(t!==i||o){let e=n._$AA;for(;e!==t;){let t=Zt(e).nextSibling;Zt(r).insertBefore(e,i),e=t}}}return n},Z=(e,t,n=e)=>(e._$AI(t,n),e),$t={},en=(e,t=$t)=>e._$AH=t,tn=e=>e._$AH,nn=e=>{e._$AR(),e._$AA.remove()},rn=(e,t,n)=>{let r=new Map;for(let i=t;i<=n;i++)r.set(e[i],i);return r},Q=Jt(class extends Yt{constructor(e){if(super(e),e.type!==qt.CHILD)throw Error(`repeat() can only be used in text expressions`)}dt(e,t,n){let r;n===void 0?n=t:t!==void 0&&(r=t);let i=[],a=[],o=0;for(let t of e)i[o]=r?r(t,o):o,a[o]=n(t,o),o++;return{values:a,keys:i}}render(e,t,n){return this.dt(e,t,n).values}update(e,[t,n,r]){let i=tn(e),{values:a,keys:o}=this.dt(t,n,r);if(!Array.isArray(i))return this.ut=o,a;let s=this.ut??=[],c=[],l,u,d=0,f=i.length-1,p=0,m=a.length-1;for(;d<=f&&p<=m;)if(i[d]===null)d++;else if(i[f]===null)f--;else if(s[d]===o[p])c[p]=Z(i[d],a[p]),d++,p++;else if(s[f]===o[m])c[m]=Z(i[f],a[m]),f--,m--;else if(s[d]===o[m])c[m]=Z(i[d],a[m]),X(e,c[m+1],i[d]),d++,m--;else if(s[f]===o[p])c[p]=Z(i[f],a[p]),X(e,i[d],i[f]),f--,p++;else if(l===void 0&&(l=rn(o,p,m),u=rn(s,d,f)),l.has(s[d])){if(l.has(s[f])){let t=u.get(o[p]),n=t===void 0?null:i[t];if(n===null){let t=X(e,i[d]);Z(t,a[p]),c[p]=t}else c[p]=Z(n,a[p]),X(e,i[d],n),i[t]=null;p++}else nn(i[f]),f--}else nn(i[d]),d++;for(;p<=m;){let t=X(e,c[m+1]);Z(t,a[p]),c[p++]=t}for(;d<=f;){let e=i[d++];e!==null&&nn(e)}return this.ut=o,en(e,c),O}}),an=class extends F{static properties={option:{attribute:!1}};createRenderRoot(){return this}updated(){let e=this.querySelector(`select`),t=this.option?.currentValue;e&&t!=null&&e.value!==String(t)&&(e.value=String(t))}render(){let e=this.option,t=Array.isArray(e.options)?e.options:[];return D`
      <label class="picker" title=${e.name||e.id}>
        <span class="picker-label">${e.name||e.id}</span>
        <select
          class="select picker-select"
          data-config-id=${e.id}
          aria-label=${e.name||e.id}
          @change=${this._on_change}
        >
          ${t.map(t=>this._render_choice(t,e.currentValue))}
        </select>
      </label>
    `}_render_choice(e,t){return e?Array.isArray(e.options)?D`
        <optgroup label=${e.name||e.group||``}>
          ${e.options.map(e=>this._render_option(e,t))}
        </optgroup>
      `:this._render_option(e,t):k}_render_option(e,t){let n=String(e.value);return D`
      <option value=${n} ?selected=${t!=null&&String(t)===n} title=${e.description||k}>
        ${e.name||n}
      </option>
    `}async _on_change(e){let t=e.currentTarget,n=this.option.currentValue;!await Y.change_config(this.option.id,t.value)&&n!=null&&(t.value=String(n))}};customElements.define(`config-picker`,an);var on=class extends F{constructor(){super(),this._store=new I(this,R)}createRenderRoot(){return this}updated(){let e=this.querySelector(`details`),t=this.querySelector(`.logs-body`);e&&e.open&&t&&(t.scrollTop=t.scrollHeight)}render(){let e=this._store.state.logs;return D`
      <details class="logs" id="logs-drawer" @toggle=${this._on_toggle}>
        <summary title="Logs" aria-label="Logs">
          <span class="logs-icon" aria-hidden="true">${Ve}</span>
          <span class="logs-count" ?hidden=${e.length===0}>${e.length}</span>
        </summary>
        <pre class="logs-body" aria-label="Server log output">${e.join(`
`)}</pre>
      </details>
    `}_on_toggle(){this.requestUpdate()}};customElements.define(`log-drawer`,on);var sn=class extends F{constructor(){super(),this._store=new I(this,R)}createRenderRoot(){return this}render(){let e=this._store.state,t=L.usage_percent(e),n=L.usage_level(e),{used:r,size:i,cost:a}=e.usage,o=e.agent.version?`${e.agent.name} ${e.agent.version}`:e.agent.name,s=`Context ${Math.round(t)}% · ${Je(r)} / ${Je(i)}`+(a?` · ${Ye(a)}`:``)+` · ${o}`;return D`
      <div class="usage" title=${s} aria-label=${s}>
        <span class="usage-text">${Math.round(t)}%</span>
        <span
          class="usage-bar"
          role="progressbar"
          aria-label="Context usage"
          aria-valuemin="0"
          aria-valuemax="100"
          aria-valuenow=${Math.round(t)}
        >
          <span class="usage-fill" data-level=${n} style="width: ${t.toFixed(1)}%"></span>
        </span>
      </div>
    `}};customElements.define(`usage-meter`,sn);var cn=class extends F{constructor(){super(),this._store=new I(this,R)}createRenderRoot(){return this}render(){let e=this._store.state;return D`
      <div class="control-strip" role="toolbar" aria-label="Session controls">
        <div class="strip-config">
          ${e.config_options.length?Q(e.config_options,e=>e.id,e=>D`<config-picker .option=${e}></config-picker>`):D`<span class="strip-muted">${e.status===`ready`?`No config options`:`Connecting…`}</span>`}
        </div>

        <div class="strip-actions">
          <usage-meter></usage-meter>
          <log-drawer></log-drawer>
          <button
            class="strip-btn"
            type="button"
            title="New chat"
            aria-label="New chat"
            ?disabled=${e.new_chat_pending}
            @click=${this._new_chat}
          >${He}</button>
          <button
            class="strip-btn"
            type="button"
            title="Restart cecli"
            aria-label="Restart cecli"
            ?disabled=${e.restart_pending}
            @click=${this._restart}
          >${Ue}</button>
        </div>
      </div>
    `}_new_chat(){Y.new_chat()}_restart(){Y.restart_server()}};customElements.define(`control-strip`,cn);var ln=class extends F{static properties={entry:{attribute:!1}};createRenderRoot(){return this}render(){let e=this.entry,t=e.options||[],n=e.resolving||e.resolved;return D`
      <article
        class="permission-card ${e.resolving?`is-submitting`:``} ${e.resolved?`is-resolved`:``}"
        data-request-id=${e.key}
      >
        <div class="perm-head">
          <span class="perm-icon" aria-hidden="true">${Ie}</span>
          <div class="perm-titles">
            <h3 class="perm-title">Permission requested</h3>
            <p class="perm-tool">${e.tool_call.title||`Tool request`}</p>
          </div>
        </div>
        <p class="perm-question">
          ${e.detail||`cecli is asking for permission to continue.`}
        </p>
        <div class="perm-options">
          ${t.length?t.map(t=>D`
                  <button
                    class="perm-option ${rt(t.kind)} ${e.chosen===String(t.optionId)?`is-chosen`:``}"
                    type="button"
                    data-option-id=${String(t.optionId)}
                    ?disabled=${n}
                    @click=${this._choose}
                  >${t.name||String(t.optionId)}</button>
                `):D`
                <button
                  class="perm-option perm-option--reject"
                  type="button"
                  ?disabled=${n}
                  @click=${this._dismiss}
                >Dismiss</button>
              `}
        </div>
        <p
          class="perm-status"
          ?hidden=${!e.resolved}
          data-kind=${e.status_kind}
        >${e.status_text}</p>
      </article>
    `}_choose(e){let t=e.currentTarget;this._emit(t.dataset.optionId)}_dismiss(){this._emit(null)}_emit(e){this.entry.resolving||this.entry.resolved||this.dispatchEvent(new CustomEvent(`permission-resolve`,{bubbles:!0,composed:!0,detail:{request_id:this.entry.request_id,option_id:e}}))}};customElements.define(`permission-card`,ln);var un=class extends F{constructor(){super(),this._store=new I(this,R)}createRenderRoot(){return this}render(){let e=this._store.state.permissions;return D`
      <div class="permission-region" ?hidden=${e.length===0}>
        ${Q(e,e=>e.key,e=>D`
            <permission-card
              .entry=${e}
              @permission-resolve=${this._on_resolve}
            ></permission-card>
          `)}
      </div>
    `}_on_resolve(e){let{request_id:t,option_id:n}=e.detail;Y.resolve_permission(t,n)}};customElements.define(`permission-region`,un);var dn=Jt(class extends Yt{constructor(e){if(super(e),e.type!==qt.ATTRIBUTE||e.name!==`class`||e.strings?.length>2)throw Error("`classMap()` can only be used in the `class` attribute and must be the only part in the attribute.")}render(e){return` `+Object.keys(e).filter(t=>e[t]).join(` `)+` `}update(e,[t]){if(this.st===void 0){this.st=new Set,e.strings!==void 0&&(this.nt=new Set(e.strings.join(` `).split(/\s/).filter(e=>e!==``)));for(let e in t)t[e]&&!this.nt?.has(e)&&this.st.add(e);return this.render(t)}let n=e.element.classList;for(let e of this.st)e in t||(n.remove(e),this.st.delete(e));for(let e in t){let r=!!t[e];r===this.st.has(e)||this.nt?.has(e)||(r?(n.add(e),this.st.add(e)):(n.remove(e),this.st.delete(e)))}return O}}),fn=class extends F{constructor(){super(),this._store=new I(this,R)}createRenderRoot(){return this}render(){return D`
      <div class="toasts" aria-live="polite" aria-atomic="false">
        ${Q(this._store.state.toasts,e=>e.id,e=>D`
            <div
              class=${dn({"toast-item":!0,"toast-item--error":e.kind===`error`,"toast-item--info":e.kind!==`error`,"is-visible":e.visible})}
              role="status"
            >${e.message}</div>
          `)}
      </div>
    `}};customElements.define(`toast-stack`,fn);var pn=class extends Yt{constructor(e){if(super(e),this.it=k,e.type!==qt.CHILD)throw Error(this.constructor.directiveName+`() can only be used in child bindings`)}render(e){if(e===k||e==null)return this._t=void 0,this.it=e;if(e===O)return e;if(typeof e!=`string`)throw Error(this.constructor.directiveName+`() called with a non-string value`);if(e===this.it)return this._t;this.it=e;let t=[e];return t.raw=t,this._t={_$litType$:this.constructor.resultType,strings:t,values:[]}}};pn.directiveName=`unsafeHTML`,pn.resultType=1;var mn=Jt(pn);function hn(e){return String(e??``).replace(/&/g,`&amp;`).replace(/</g,`&lt;`).replace(/>/g,`&gt;`).replace(/"/g,`&quot;`).replace(/'/g,`&#39;`)}function gn(e){let t=hn(e).split(`
`),n=[],r=0;for(;r<t.length;){let e=t[r];if(!e.trim()){r+=1;continue}let i=/^```([\w+#.-]*)\s*$/.exec(e.trim());if(i){let e=i[1]||``,a=[];for(r+=1;r<t.length&&!/^```\s*$/.test(t[r].trim());)a.push(t[r]),r+=1;r<t.length&&(r+=1),n.push(vn(a.join(`
`),e));continue}let a=/^(#{1,3})\s+(.+)$/.exec(e);if(a){let e=a[1].length;n.push(`<h${e}>${$(a[2])}</h${e}>`),r+=1;continue}if(/^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(e)){n.push(`<hr>`),r+=1;continue}if(/^\s*&gt;\s?/.test(e)){let e=[];for(;r<t.length&&/^\s*&gt;\s?/.test(t[r]);)e.push(t[r].replace(/^\s*&gt;\s?/,``)),r+=1;n.push(`<blockquote>${$(e.join(`
`)).replace(/\n/g,`<br>`)}</blockquote>`);continue}if(/^\s*[-*+]\s+/.test(e)){let e=[];for(;r<t.length&&/^\s*[-*+]\s+/.test(t[r]);)e.push($(t[r].replace(/^\s*[-*+]\s+/,``))),r+=1;n.push(`<ul>${e.map(e=>`<li>${e}</li>`).join(``)}</ul>`);continue}if(/^\s*\d+[.)]\s+/.test(e)){let e=[];for(;r<t.length&&/^\s*\d+[.)]\s+/.test(t[r]);)e.push($(t[r].replace(/^\s*\d+[.)]\s+/,``))),r+=1;n.push(`<ol>${e.map(e=>`<li>${e}</li>`).join(``)}</ol>`);continue}let o=[];for(;r<t.length&&t[r].trim()&&!_n(t[r]);)o.push(t[r]),r+=1;o.length?n.push(`<p>${$(o.join(`
`)).replace(/\n/g,`<br>`)}</p>`):r+=1}return n.join(``)}function _n(e){return/^```/.test(e.trim())||/^#{1,3}\s+/.test(e)||/^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(e)||/^\s*&gt;\s?/.test(e)||/^\s*[-*+]\s+/.test(e)||/^\s*\d+[.)]\s+/.test(e)}function vn(e,t){return`<div class="code-block"><div class="code-head"><span class="code-lang">${t?hn(t):`text`}</span><button type="button" class="code-copy" aria-label="Copy code">Copy</button></div><pre><code>${e}</code></pre></div>`}function $(e){return e.split(/(`[^`\n]+`)/g).map((e,t)=>t%2==1?`<code>${e.slice(1,-1)}</code>`:yn(e)).join(``)}function yn(e){let t=[],n=e.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,(e,n,r)=>(t.push({label:n,url:r}),`\u0000link${t.length-1}\u0000`));return n=bn(n),n=n.replace(/\u0000link(\d+)\u0000/g,(e,n)=>{let r=t[Number(n)];return r?`<a href="${r.url}" target="_blank" rel="noopener noreferrer">${bn(r.label)}</a>`:``}),n}function bn(e){return e.replace(/\*\*([^*]+)\*\*/g,`<strong>$1</strong>`).replace(/__([^_]+)__/g,`<strong>$1</strong>`).replace(/~~([^~]+)~~/g,`<del>$1</del>`).replace(/(^|[^*])\*([^*\n]+)\*/g,`$1<em>$2</em>`).replace(/(^|[^\w])_([^_\n]+)_(?!\w)/g,`$1<em>$2</em>`)}var xn=class extends F{static properties={text:{type:String},streaming:{type:Boolean}};constructor(){super(),this.text=``,this.streaming=!1,this._rendered=``,this._timer=null,this._caret_for=null}createRenderRoot(){return this}willUpdate(e){(e.has(`text`)||e.has(`streaming`))&&(this.streaming?this._schedule_render():this._render_now())}updated(){this.streaming?this._attach_caret():this._remove_caret()}disconnectedCallback(){clearTimeout(this._timer),this._timer=null,super.disconnectedCallback()}render(){return D`
      <div
        class="md ${this.streaming?`is-streaming`:``}"
        @click=${this._on_click}
      >${mn(this._rendered)}</div>
    `}_schedule_render(){this._timer||=setTimeout(()=>{this._timer=null,this._rendered=gn(this.text),this.requestUpdate()},60)}_render_now(){clearTimeout(this._timer),this._timer=null,this._rendered=gn(this.text)}_attach_caret(){if(this._caret_for===this._rendered)return;let e=this.querySelector(`.md`);if(!e)return;let t=document.createElement(`span`);t.className=`stream-caret`,t.setAttribute(`aria-hidden`,`true`);let n=e.lastElementChild;n&&/^(P|LI|H1|H2|H3|BLOCKQUOTE)$/.test(n.tagName)?n.appendChild(t):e.appendChild(t),this._caret_for=this._rendered}_remove_caret(){for(let e of this.querySelectorAll(`.stream-caret`))e.remove();this._caret_for=null}_on_click(e){let t=e.target.closest(`.code-copy`);t&&this._copy_code(t)}async _copy_code(e){let t=e.closest(`.code-block`),n=t?t.querySelector(`code`):null;if(n){try{await navigator.clipboard.writeText(n.textContent)}catch{Sn(n.textContent)}Cn(e,`Copied`)}}};function Sn(e){let t=document.createElement(`textarea`);t.value=e,t.setAttribute(`readonly`,`readonly`),t.style.position=`fixed`,t.style.opacity=`0`,document.body.appendChild(t),t.select();try{document.execCommand(`copy`)}catch{return}finally{t.remove()}}function Cn(e,t){let n=e.textContent;e.textContent=t,setTimeout(()=>{e.isConnected&&(e.textContent=n)},1400)}customElements.define(`markdown-view`,xn);var wn=class extends F{static properties={part:{attribute:!1}};createRenderRoot(){return this}render(){let e=this.part.entries||[],t=e.filter(e=>e.status===`completed`).length;return D`
      <article class="plan-card" ?hidden=${e.length===0}>
        <div class="plan-head">
          <span>Plan</span>
          <span class="plan-count badge badge-ghost">${t}/${e.length}</span>
        </div>
        <ul class="plan-list">
          ${e.map(e=>D`
              <li class="plan-item" data-status=${e.status}>
                <span class="plan-mark" aria-hidden="true"></span>
                <span class="plan-text">${e.content}</span>
              </li>
            `)}
        </ul>
      </article>
    `}};customElements.define(`plan-card`,wn);var Tn=class extends F{static properties={part:{attribute:!1}};createRenderRoot(){return this}render(){return D`
      <details class="thought" ?open=${this.part.open} @toggle=${this._on_toggle}>
        <summary>Thinking</summary>
        <div class="thought-text">${this.part.text}</div>
      </details>
    `}_on_toggle(e){let t=e.currentTarget.open;t!==this.part.open&&Y.set_thought_open(this.part.id,t)}};customElements.define(`thought-block`,Tn);var En=class extends F{static properties={part:{attribute:!1}};constructor(){super(),this._open=!1}createRenderRoot(){return this}willUpdate(){this._has_output()||(this._open=!1)}render(){let e=this._has_output(),t=$e(this.part.content_text),n=Fe[this.part.kind]||Fe.other;return D`
      <article class="tool-card ${this._open?`is-open`:``}" data-tool-id=${this.part.tool_id}>
        <div class="tool-head">
          <span class="tool-icon" data-kind=${this.part.kind} aria-hidden="true">${n}</span>
          <div class="tool-title-wrap">
            <span class="tool-title">${this.part.title}</span>
            <span class="tool-locations">
              ${this._locations().map(e=>D`
                  <span class="tool-loc" title=${e.path}>${ot(e)}</span>
                `)}
            </span>
          </div>
          <span class="chip badge badge-ghost" data-status=${this.part.status}>
            ${nt(this.part.status)}
          </span>
          <button
            class="tool-toggle"
            type="button"
            aria-label="Toggle tool output"
            aria-expanded=${String(this._open&&e)}
            ?disabled=${!e}
            @click=${this._toggle}
          >${Le}</button>
        </div>
        <div class="tool-body" ?hidden=${!this._open||!e}>
          <pre><code>${t}</code></pre>
        </div>
      </article>
    `}_locations(){return(this.part.locations||[]).filter(e=>e&&e.path).slice(0,4)}_has_output(){return $e(this.part.content_text).length>0}_toggle(){this._has_output()&&(this._open=!this._open,this.requestUpdate(),this._open&&R.state.auto_scroll&&this.dispatchEvent(new CustomEvent(`transcript-layout`,{bubbles:!0,composed:!0})))}};customElements.define(`tool-card`,En);var Dn=class extends F{static properties={item:{attribute:!1}};createRenderRoot(){return this}render(){return D`
      <div class="msg msg--assistant" data-turn=${this.item.turn}>
        <div class="msg-avatar" aria-hidden="true">c</div>
        <div class="msg-body">
          ${Q(this.item.parts,e=>e.id,e=>this._render_part(e))}
        </div>
      </div>
    `}_render_part(e){switch(e.type){case`text`:return D`<markdown-view
          .text=${e.text}
          .streaming=${e.streaming}
        ></markdown-view>`;case`thought`:return D`<thought-block .part=${e}></thought-block>`;case`tool`:return D`<tool-card .part=${e}></tool-card>`;case`plan`:return D`<plan-card .part=${e}></plan-card>`;default:return D``}}};customElements.define(`assistant-turn`,Dn);var On=`                     ▒▒╗▒▒╗
 ▒▒▒▒▒╗ ▒▒▒▒▒╗ ▒▒▒▒▒╗▒▒║╚═╝
▒▒╔═══╝▒▒▓▓▓▒║▒▒╔═══╝▒▒║▒▒╗
▒▒║    ▒▒╔═══╝▒▒║    ▒▒║▒▒║
╚▒▒▒▒▒╗╚▒▒▒▒▒╗╚▒▒▒▒▒╗▒▒║▒▒║
 ╚════╝ ╚════╝ ╚════╝╚═╝╚═╝`,kn=class extends F{createRenderRoot(){return this}render(){return D`<pre class="cecli-logo" role="img" aria-label="cecli">${On}</pre>`}};customElements.define(`brand-logo`,kn);var An=[{prompt:`Explain the structure of this repository and where I should start reading.`,title:`Explain this repo`},{prompt:`Find a likely bug in the current changes and explain how to fix it.`,title:`Find a bug`},{prompt:`Run the test suite and summarise any failures with likely causes.`,title:`Run the tests`}],jn=class extends F{createRenderRoot(){return this}render(){return D`
      <section class="empty-state">
        <brand-logo></brand-logo>
        <h1>What can I help you build?</h1>
        <p>Ask a question, request a change, or start with one of these.</p>
        <div class="examples">
          ${An.map(e=>D`
              <button
                class="example"
                type="button"
                data-prompt=${e.prompt}
                @click=${this._on_example}
              >
                <span class="example-glyph" aria-hidden="true"></span>
                <span class="example-text"><strong>${e.title}</strong></span>
              </button>
            `)}
        </div>
      </section>
    `}_on_example(e){let t=e.currentTarget;this.dispatchEvent(new CustomEvent(`example-select`,{bubbles:!0,composed:!0,detail:{prompt:t.dataset.prompt}}))}};customElements.define(`empty-state`,jn);var Mn=class extends F{static properties={text:{type:String}};constructor(){super(),this.text=``}createRenderRoot(){return this}render(){return D`
      <div class="msg msg--user">
        <div class="bubble">${this.text}</div>
      </div>
    `}};customElements.define(`user-message`,Mn);var Nn=class extends F{constructor(){super(),this._store=new I(this,R),this._observer=null}createRenderRoot(){return this}firstUpdated(){let e=this._transcript();e&&(this._observer=new MutationObserver(()=>this._maybe_autoscroll()),this._observer.observe(e,{childList:!0,subtree:!0,characterData:!0}),this._resize_observer=new ResizeObserver(()=>this._maybe_autoscroll()),this._resize_observer.observe(e))}disconnectedCallback(){this._observer&&this._observer.disconnect(),this._observer=null,this._resize_observer&&this._resize_observer.disconnect(),this._resize_observer=null,this._scroll_timer&&clearTimeout(this._scroll_timer),this._scroll_timer=null,super.disconnectedCallback()}updated(){this._maybe_autoscroll(),queueMicrotask(()=>this._maybe_autoscroll()),this._scroll_timer&&clearTimeout(this._scroll_timer),this._scroll_timer=setTimeout(()=>{this._scroll_timer=null,this._maybe_autoscroll()},0)}render(){let e=this._store.state;return D`
      <div
        class="transcript"
        role="log"
        aria-live="polite"
        aria-relevant="additions text"
        tabindex="0"
        @scroll=${this._on_scroll}
        @transcript-layout=${this._maybe_autoscroll}
      >
        <empty-state
          ?hidden=${L.has_transcript(e)}
          @example-select=${this._on_example}
        ></empty-state>
        ${Q(e.transcript,e=>e.id,e=>e.type===`user`?D`<user-message .text=${e.text}></user-message>`:D`<assistant-turn .item=${e}></assistant-turn>`)}
      </div>
      <button class="jump-pill" type="button" ?hidden=${e.auto_scroll} @click=${this._jump}>
        <span aria-hidden="true">↓</span> Jump to latest
      </button>
    `}_transcript(){return this.querySelector(`.transcript`)}_near_bottom(){let e=this._transcript();return!e||e.scrollHeight-e.scrollTop-e.clientHeight<80}_scroll_to_bottom(e){let t=this._transcript();t&&t.scrollTo({top:t.scrollHeight,behavior:e?`smooth`:`auto`})}_maybe_autoscroll(){this._store.state.auto_scroll&&this._scroll_to_bottom(!1)}_on_scroll(){let e=this._near_bottom();this._store.state.auto_scroll!==e&&Y.set_auto_scroll(e)}_jump(){Y.jump_to_latest(),this._scroll_to_bottom(!0)}_on_example(e){Y.fill_composer(e.detail&&e.detail.prompt)}};customElements.define(`transcript-view`,Nn);var Pn=class extends F{createRenderRoot(){return this}render(){return D`
      <app-backdrop></app-backdrop>
      <div class="app-shell">
        <app-header></app-header>
        <main class="chat-panel">
          <transcript-view></transcript-view>
          <permission-region></permission-region>
          <div class="composer-dock">
            <composer-bar></composer-bar>
            <control-strip></control-strip>
          </div>
        </main>
      </div>
      <toast-stack></toast-stack>
    `}};customElements.define(`cecli-app`,Pn),Y.start();