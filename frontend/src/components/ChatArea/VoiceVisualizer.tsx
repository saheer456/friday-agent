import { useEffect, useRef } from 'react';
import styles from './VoiceVisualizer.module.css';

interface VoiceVisualizerProps {
  isSpeaking: boolean;
}

interface Particle {
  x: number;
  y: number;
  z: number;
}

export function VoiceVisualizer({ isSpeaking }: VoiceVisualizerProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const requestRef = useRef<number | null>(null);

  useEffect(() => {
    if (!isSpeaking) {
      if (requestRef.current) {
        cancelAnimationFrame(requestRef.current);
        requestRef.current = null;
      }
      return;
    }

    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Fixed internal dimensions for standard visualizer scaling
    const W = 180;
    const H = 180;
    canvas.width = W;
    canvas.height = H;

    const centerX = W / 2;
    const centerY = H / 2;

    // Generate 65 particles on a 3D sphere surface
    const numParticles = 65;
    const particles: Particle[] = [];
    const baseRadius = 45;

    for (let i = 0; i < numParticles; i++) {
      const theta = Math.acos(Math.random() * 2 - 1);
      const phi = Math.random() * Math.PI * 2;
      particles.push({
        x: baseRadius * Math.sin(theta) * Math.cos(phi),
        y: baseRadius * Math.sin(theta) * Math.sin(phi),
        z: baseRadius * Math.cos(theta),
      });
    }

    // Local state for rotation and sound-level interpolation
    let angleX = 0;
    let angleY = 0;
    let smoothVol = 0;

    const render = () => {
      // Read current voice volume from CSS property set by edge-tts/Kokoro stream
      const rawVol = parseFloat(document.documentElement.style.getPropertyValue('--voice-volume') || '0');
      
      // Smooth interpolation for fluid reactions
      smoothVol = smoothVol * 0.85 + rawVol * 0.15;

      // Clear canvas with transparent background
      ctx.clearRect(0, 0, W, H);

      // 1. Draw glowing central radial aura
      const radialGlow = ctx.createRadialGradient(centerX, centerY, 5, centerX, centerY, 65 * (1 + smoothVol * 0.006));
      radialGlow.addColorStop(0, 'rgba(0, 195, 255, 0.15)');
      radialVol: {
        radialGlow.addColorStop(0.3, 'rgba(0, 195, 255, 0.05)');
        radialGlow.addColorStop(1, 'rgba(0, 0, 0, 0)');
      }
      ctx.fillStyle = radialGlow;
      ctx.beginPath();
      ctx.arc(centerX, centerY, 90, 0, Math.PI * 2);
      ctx.fill();

      // Dynamic variables matching volume level
      const volumeFactor = 1 + smoothVol * 0.008; // scale threshold
      const currentRadius = baseRadius * volumeFactor;
      const rotSpeedX = 0.006 + smoothVol * 0.0003;
      const rotSpeedY = 0.008 + smoothVol * 0.0004;

      // Update rotation angles
      angleX += rotSpeedX;
      angleY += rotSpeedY;

      const cosX = Math.cos(rotSpeedX);
      const sinX = Math.sin(rotSpeedX);
      const cosY = Math.cos(rotSpeedY);
      const sinY = Math.sin(rotSpeedY);

      // Rotate coordinates and project them to 2D
      const projected = particles.map(p => {
        // Rotate around Y axis
        let x1 = p.x * cosY - p.z * sinY;
        let z1 = p.z * cosY + p.x * sinY;

        // Rotate around X axis
        let y2 = p.y * cosX - z1 * sinX;
        let z2 = z1 * cosX + p.y * sinX;

        // Save rotated position
        p.x = x1;
        p.y = y2;
        p.z = z2;

        // Perspective projection parameters
        const fov = 160;
        const cameraDistance = 90;
        const factor = fov / (z2 + cameraDistance + currentRadius);

        // Micro vibration based on sound volume
        const jitter = (Math.random() - 0.5) * (smoothVol * 0.12);

        return {
          sx: x1 * factor * volumeFactor + centerX + jitter,
          sy: y2 * factor * volumeFactor + centerY + jitter,
          sz: z2,
        };
      });

      // 2. Draw connections (hologram network mesh)
      ctx.lineWidth = 0.5;
      const maxDistance = 42 * volumeFactor;

      for (let i = 0; i < numParticles; i++) {
        const p1 = projected[i];
        for (let j = i + 1; j < numParticles; j++) {
          const p2 = projected[j];

          // Compute Euclidean distance in 3D
          const dx = particles[i].x - particles[j].x;
          const dy = particles[i].y - particles[j].y;
          const dz = particles[i].z - particles[j].z;
          const dist = Math.sqrt(dx * dx + dy * dy + dz * dz) * volumeFactor;

          if (dist < maxDistance) {
            // Compute alpha based on distance and depth (closer to front = brighter)
            const proximityAlpha = 1 - dist / maxDistance;
            const frontAlpha = (p1.sz + p2.sz + 2 * currentRadius) / (4 * currentRadius);
            const lineAlpha = proximityAlpha * frontAlpha * 0.35;

            ctx.strokeStyle = `rgba(0, 195, 255, ${lineAlpha})`;
            ctx.beginPath();
            ctx.moveTo(p1.sx, p1.sy);
            ctx.lineTo(p2.sx, p2.sy);
            ctx.stroke();
          }
        }
      }

      // 3. Draw nodes (points)
      for (let i = 0; i < numParticles; i++) {
        const p = projected[i];
        
        // Depth mapping for size and opacity
        const depthRatio = (p.sz + currentRadius) / (2 * currentRadius); // 0 to 1
        const dotSize = (0.8 + depthRatio * 1.5) * (1 + smoothVol * 0.005);
        const dotAlpha = (0.2 + depthRatio * 0.7) * (0.6 + smoothVol * 0.01);

        ctx.fillStyle = `rgba(0, 210, 255, ${dotAlpha})`;
        ctx.beginPath();
        ctx.arc(p.sx, p.sy, dotSize, 0, Math.PI * 2);
        ctx.fill();
      }

      requestRef.current = requestAnimationFrame(render);
    };

    requestRef.current = requestAnimationFrame(render);

    return () => {
      if (requestRef.current) cancelAnimationFrame(requestRef.current);
    };
  }, [isSpeaking]);

  return (
    <div className={`${styles.container} ${isSpeaking ? styles.visible : ''}`}>
      <canvas ref={canvasRef} className={styles.canvas} />
      <div className={styles.pulseCore} style={{
        transform: `translate(-50%, -50%) scale(calc(1 + var(--voice-volume, 0) * 0.005))`
      }} />
    </div>
  );
}
