"use client";

// Ported directly from PersonalWebsite's src/components/STLViewer.tsx —
// same library choices (three.js STLLoader + @react-three/fiber + drei),
// same hover-to-rotate / orbit-controls behavior.

import { Canvas, useFrame, useLoader } from "@react-three/fiber";
import { OrbitControls, Bounds } from "@react-three/drei";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { Suspense, useMemo, useRef } from "react";
import { BufferGeometry, Group } from "three";

function FitOnLoad({ children }: { children: React.ReactNode }) {
  return (
    <Bounds fit clip observe margin={1.2}>
      {children}
    </Bounds>
  );
}

function Model({ url }: { url: string }) {
  const geometry = useLoader(STLLoader, url) as BufferGeometry;
  const mat = useMemo(() => ({ color: "#00ff00", roughness: 0.6, metalness: 0.1 }), []);
  return (
    <mesh geometry={geometry} rotation={[-Math.PI / 2, 0, 0]}>
      <meshStandardMaterial {...mat} />
    </mesh>
  );
}

function RotatingModel({ url, hover }: { url: string; hover: boolean }) {
  const groupRef = useRef<Group>(null);

  useFrame((_, delta) => {
    if (hover && groupRef.current) {
      groupRef.current.rotation.y += delta * 0.6;
    }
  });

  return (
    <group ref={groupRef}>
      <FitOnLoad>
        <Model url={url} />
      </FitOnLoad>
    </group>
  );
}

export default function STLViewer({
  url,
  height = "50vh",
  hover = false,
  controls = true,
  zoom = true,
}: {
  url: string;
  height?: number | string;
  hover?: boolean;
  controls?: boolean;
  zoom?: boolean;
}) {
  return (
    <div style={{ width: "100%", height }}>
      <Canvas camera={{ position: [4, 3, 5], fov: 50 }}>
        <ambientLight intensity={0.6} />
        <directionalLight position={[8, 10, 6]} intensity={0.9} />
        <Suspense fallback={null}>
          <RotatingModel url={url} hover={hover} />
        </Suspense>
        {controls && <OrbitControls enableZoom={zoom} />}
      </Canvas>
    </div>
  );
}
