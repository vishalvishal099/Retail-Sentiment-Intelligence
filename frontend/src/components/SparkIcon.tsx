interface SparkIconProps {
  size?: number;
  className?: string;
  color?: string;
}

// Generic 6-petal "spark" mark inspired by retail brand identity.
// Not the trademarked Walmart Spark — colors and proportions are independent.
export default function SparkIcon({ size = 28, className = '', color = '#FFC220' }: SparkIconProps) {
  const petals = Array.from({ length: 6 }, (_, i) => i * 60);
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      className={className}
      aria-hidden="true"
    >
      <g transform="translate(32 32)">
        {petals.map((deg) => (
          <ellipse
            key={deg}
            cx="0"
            cy="-20"
            rx="3.6"
            ry="11"
            fill={color}
            transform={`rotate(${deg})`}
          />
        ))}
      </g>
    </svg>
  );
}
