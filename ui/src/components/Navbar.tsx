import { Link, NavLink } from "react-router-dom";
import { useTheme } from "../hooks/useTheme";

const Navbar = () => {
	const { theme, toggleTheme } = useTheme();

	return (
		<nav className="navbar">
			<div className="container-fluid">
				<Link to="/" className="navbar-brand">
					LLM System
				</Link>

				<div className="d-flex align-items-center gap-3">
					<ul className="navbar-nav flex-row gap-3 mb-0">
						<li className="nav-item">
							<NavLink
								to="/"
								className={({ isActive }) =>
									isActive ? "nav-link active" : "nav-link"
								}
							>
								Home
							</NavLink>
						</li>

						<li className="nav-item">
							<NavLink
								to="/setting"
								className={({ isActive }) =>
									isActive ? "nav-link active" : "nav-link"
								}
							>
								Setting
							</NavLink>
						</li>
					</ul>

					<button
						type="button"
						className="theme-toggle"
						onClick={toggleTheme}
						aria-label="Toggle dark mode"
					>
						{theme === "light" ? "Dark mode" : "Light mode"}
					</button>
				</div>
			</div>
		</nav>
	);
};

export default Navbar;
