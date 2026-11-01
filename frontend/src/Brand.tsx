import logo from "./img/logo.png";

// The AllStarLink logo (the same image the appliance uses for Cockpit's
// login page). Its text is black, so it sits on a light tile in the dark
// top bar.
export function Logo() {
  return <img className="asl-logo" src={logo} alt="AllStarLink" />;
}

// The name block on the login card. The full logo is shown just above the
// card, so it is not repeated here.
export function Brand({ subtitle }: { subtitle: string }) {
  return (
    <div className="asl-brand">
      <div>
        <b>AllStarLink</b>
        <span>{subtitle}</span>
      </div>
    </div>
  );
}
