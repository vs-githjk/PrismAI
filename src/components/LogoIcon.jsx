const LogoIcon = ({ className, style }) => (
  <svg
    viewBox="0 0 1386 1286"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={style}
    aria-hidden="true"
  >
    {/* Center gradient triangle — static */}
    <path
      d="M662.34 997.5C675.811 1020.83 709.49 1020.83 722.961 997.5L922.147 652.5C935.619 629.167 918.779 600 891.836 600H493.465C466.522 600 449.682 629.167 463.154 652.5L662.34 997.5Z"
      fill="url(#logo-grad)"
    />
    {/* Three orbiting white triangles */}
    <g className="logo-spinner">
      <path
        d="M632.029 105C658.972 58.3333 726.329 58.3333 753.272 105L910.889 378C937.832 424.667 904.153 483 850.267 483H535.034C481.148 483 447.469 424.667 474.412 378L632.029 105Z"
        fill="white"
      />
      <path
        d="M1002.68 747C1029.62 700.333 1096.98 700.333 1123.92 747L1281.54 1020C1308.48 1066.67 1274.8 1125 1220.92 1125H905.683C851.797 1125 818.118 1066.67 845.061 1020L1002.68 747Z"
        fill="white"
      />
      <path
        d="M261.378 747C288.321 700.333 355.679 700.333 382.622 747L540.238 1020C567.181 1066.67 533.503 1125 479.617 1125H164.383C110.497 1125 76.8186 1066.67 103.762 1020L261.378 747Z"
        fill="white"
      />
    </g>
    <defs>
      <linearGradient id="logo-grad" x1="433.45" y1="602" x2="739.05" y2="931.2" gradientUnits="userSpaceOnUse">
        <stop stopColor="#F94144" />
        <stop offset="0.143" stopColor="#F3722C" />
        <stop offset="0.28" stopColor="#F8961E" />
        <stop offset="0.42" stopColor="#F9C74F" />
        <stop offset="0.56" stopColor="#90BE6D" />
        <stop offset="0.7" stopColor="#43AA8B" />
        <stop offset="0.85" stopColor="#577590" />
      </linearGradient>
    </defs>
  </svg>
);

export default LogoIcon;
