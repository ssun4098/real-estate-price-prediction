import React from 'react';

// Shared geometry keeps each map marker recognizable in the legend as well.
// Shapes, rather than color alone, identify the five facility types.
export function FacilityGlyph({kind,...props}){
 const marks={
  school:<><path d="M3 10L12 3L21 10M5 9V21H19V9M2 21H22M10 21V15H14V21"/><path d="M7 12H8M16 12H17M7 16H8M16 16H17M12 3V1H17V4H13"/></>,
  mountain:<><path d="M2 21L10 5L15 14L18 9L23 21ZM6.5 12L10 14L12.5 10M15 14L18 16L20 13"/></>,
  river:<><path d="M9 2C2 5 17 7 10 11S4 17 10 22M15 2C8 5 23 7 16 11S10 17 16 22M2 7H5M20 17H23"/></>,
  industrial:<><path d="M3 21V11L9 7V11L15 7V11H21V21ZM17 11V3H20V11M7 15H8M12 15H13M17 15H18M7 18H8M12 18H13M17 18H18"/></>,
  sewage:<><path d="M2 13V21H22V13M2 13C4 10 7 16 10 13S16 10 18 13S21 14 22 13M2 17C4 14 7 20 10 17S16 14 18 17S21 18 22 17M16 2C16 2 12 6 12 8A4 4 0 0 0 20 8C20 6 16 2 16 2ZM3 11V5H8"/></>,
 };
 return <g fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" {...props}>{marks[kind]||<path d="M4 4H20V20H4ZM8 8H16M8 12H16M8 16H12"/>}</g>;
}

export function FacilityIcon({kind,color,className='',size=19}){
 return <svg className={`v5-facility-icon ${className}`} viewBox="0 0 24 24" width={size} height={size} aria-hidden="true" focusable="false" style={{color}}><FacilityGlyph kind={kind}/></svg>;
}
