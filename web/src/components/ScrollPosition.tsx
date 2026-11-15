import { useEffect, useRef } from 'react'
import { useLocation, useNavigationType } from 'react-router'

const positions = new Map<string,number>()
/** 새 화면은 처음부터, 뒤로 가기는 읽던 위치로. 늦게 도착한 SSE도 짧게 기다린다. */
export function ScrollPosition() {
  const {key,pathname,hash} = useLocation()
  const navigation = useNavigationType()
  const restoring = useRef(false)
  useEffect(()=>{
    const previous = window.history.scrollRestoration
    window.history.scrollRestoration='manual'
    return ()=>{window.history.scrollRestoration=previous}
  },[])
  useEffect(()=>{
    if (hash) return
    const target = navigation === 'POP' ? positions.get(key) ?? 0 : 0
    let frame=0
    let cancelled=false
    restoring.current=true
    const cancel=()=>{cancelled=true;cancelAnimationFrame(frame);restoring.current=false}
    const restore=(attempt=0)=>{
      if(cancelled)return
      const max=Math.max(0,document.documentElement.scrollHeight-window.innerHeight)
      window.scrollTo({top:Math.min(target,max),behavior:'instant'})
      if(max>=target || attempt>=90){restoring.current=false;return}
      frame=requestAnimationFrame(()=>restore(attempt+1))
    }
    frame=requestAnimationFrame(()=>restore())
    window.addEventListener('wheel',cancel,{passive:true})
    window.addEventListener('touchstart',cancel,{passive:true})
    window.addEventListener('pointerdown',cancel,{passive:true})
    window.addEventListener('keydown',cancel)
    return ()=>{cancel();window.removeEventListener('wheel',cancel);window.removeEventListener('touchstart',cancel);window.removeEventListener('pointerdown',cancel);window.removeEventListener('keydown',cancel)}
  },[key,pathname,hash,navigation])
  useEffect(()=>{
    const remember=()=>{
      if(restoring.current)return
      positions.set(key,window.scrollY)
      if(positions.size>50)positions.delete(positions.keys().next().value!)
    }
    window.addEventListener('scroll',remember,{passive:true})
    return ()=>window.removeEventListener('scroll',remember)
  },[key])
  return null
}
