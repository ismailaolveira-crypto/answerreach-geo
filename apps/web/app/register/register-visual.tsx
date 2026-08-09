import { RegisterShowcaseCarousel } from "./register-showcase-carousel";

export function RegisterVisual() {
  return (
    <section className="cq-register-visual" aria-labelledby="register-visual-title">
      <div className="cq-register-visual-copy">
        <h2 id="register-visual-title">从品牌到证据，<br />建立你的 <em>GEO 观测空间</em></h2>
        <p>账号、数据与观测结果默认隔离。</p>
      </div>

      <div className="cq-register-product-stage">
        <RegisterShowcaseCarousel />
        <span className="cq-register-crystal"><i /><b /><em /></span>
      </div>
    </section>
  );
}

export function RegisterLightTrails() {
  return (
    <div className="cq-register-trail-field" aria-hidden="true">
      <svg viewBox="0 0 1536 1024" preserveAspectRatio="none">
        <defs>
          <linearGradient id="cq-register-ribbon" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stopColor="#d8e8ff" />
            <stop offset=".32" stopColor="#6fdcff" />
            <stop offset=".62" stopColor="#5682ff" />
            <stop offset=".82" stopColor="#a57cff" />
            <stop offset="1" stopColor="#8bdcff" />
          </linearGradient>
          <linearGradient id="cq-register-ribbon-soft" x1="0" y1="1" x2="1" y2="0">
            <stop offset="0" stopColor="#ffffff" />
            <stop offset=".25" stopColor="#7ee7ff" />
            <stop offset=".58" stopColor="#8d9cff" />
            <stop offset="1" stopColor="#7aa8ff" />
          </linearGradient>
          <filter id="cq-register-ribbon-blur" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="7" />
          </filter>
          <filter id="cq-register-ribbon-glow" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="2.5" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>

        <g className="cq-register-trails-soft" fill="none" filter="url(#cq-register-ribbon-blur)">
          <path d="M-90 843 C165 760 315 1004 557 858 C716 762 638 600 422 686 C259 752 226 878 34 955" />
          <path d="M-70 914 C162 816 288 1018 518 887 C685 792 705 669 589 584 C509 525 466 470 594 390 C704 322 799 329 932 331" />
          <path d="M113 622 C377 614 518 488 622 389 C733 283 820 306 960 332" />
        </g>

        <g className="cq-register-trails-static" fill="none" filter="url(#cq-register-ribbon-glow)">
          <path d="M-88 868 C161 769 329 990 559 850 C721 752 637 596 424 686 C262 753 226 878 39 958" />
          <path d="M-68 910 C167 806 292 1008 518 878 C676 787 707 665 590 582 C503 520 474 470 595 392 C711 318 795 327 960 331" />
          <path d="M-37 801 C208 733 344 940 558 824 C691 752 682 638 584 566 C489 497 488 447 596 380 C706 312 809 324 966 331" />
          <path d="M110 628 C376 619 505 502 622 395 C733 293 819 306 972 332" />
          <path d="M141 653 C387 637 514 525 632 410 C738 307 833 313 976 333" />
        </g>

        <g className="cq-register-trails-motion" fill="none" filter="url(#cq-register-ribbon-glow)">
          <path d="M-68 910 C167 806 292 1008 518 878 C676 787 707 665 590 582 C503 520 474 470 595 392 C711 318 795 327 960 331" />
          <path d="M110 628 C376 619 505 502 622 395 C733 293 819 306 972 332" />
          <path d="M-88 868 C161 769 329 990 559 850 C721 752 637 596 424 686 C262 753 226 878 39 958" />
        </g>
      </svg>
      <i className="cq-register-spark is-one" /><i className="cq-register-spark is-two" />
      <i className="cq-register-spark is-three" /><i className="cq-register-spark is-four" />
      <i className="cq-register-spark is-five" /><i className="cq-register-spark is-six" />
    </div>
  );
}
