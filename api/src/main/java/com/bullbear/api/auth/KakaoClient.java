package com.bullbear.api.auth;

/** 인가 코드로 카카오 회원번호를 얻는다. 테스트에서는 가짜로 바꾼다. */
public interface KakaoClient {

	/** @return 카카오 회원번호. 이름·이메일 같은 동의 항목은 받지 않는다 */
	String userId(String code, String redirectUri);
}
