import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, ApiError } from '../lib/api'

/** 닉네임 입력. 저장하면 내 정보·랭킹을 새로 고치고 onDone을 부른다 (마이·랭킹 화면 공용) */
export function NicknameForm({ initial, onDone, className = '' }: { initial: string; onDone: () => void; className?: string }) {
  const queryClient = useQueryClient()
  const [name, setName] = useState(initial)
  const save = useMutation({
    mutationFn: () => api.setNickname(name),
    onSuccess: (m) => {
      queryClient.setQueryData(['me'], m)
      queryClient.invalidateQueries({ queryKey: ['ranking'] })
      onDone()
    },
  })
  return (
    <form
      className={`flex flex-col gap-2 ${className}`}
      onSubmit={(e) => {
        e.preventDefault()
        save.mutate()
      }}
    >
      <label htmlFor="nick" className="text-xs text-sub">
        한글·영문·숫자 2~10자
      </label>
      <div className="flex gap-2">
        <input
          id="nick"
          autoFocus
          value={name}
          maxLength={10}
          onChange={(e) => setName(e.target.value)}
          className="min-h-11 min-w-0 flex-1 rounded-xl bg-surface-2 px-3 text-[15px] outline-none focus:ring-1 focus:ring-point"
        />
        <button type="submit" disabled={save.isPending} className="min-h-11 rounded-xl bg-point px-4 text-[14px] font-bold text-on-point disabled:opacity-50">
          저장
        </button>
        <button type="button" onClick={onDone} className="min-h-11 rounded-xl px-2 text-[14px] text-sub">
          취소
        </button>
      </div>
      {save.error && (
        <p className="text-[13px] font-bold text-up-ink">
          {save.error instanceof ApiError ? save.error.message : '저장하지 못했어요'}
        </p>
      )}
    </form>
  )
}
