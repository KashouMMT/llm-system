import { Link, NavLink } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { useTheme } from "../hooks/useTheme";

const Navbar = () => {
	const { theme, toggleTheme } = useTheme();
	const auth = useAuth();

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

					{auth.status === "authenticated" && (
						<>
							<span className="navbar-user">
								{auth.user.username}
							</span>

							<button
								type="button"
								className="theme-toggle"
								onClick={() => {
									void auth.logout();
								}}
							>
								Sign out
							</button>
						</>
					)}
				</div>
			</div>
		</nav>
	);
};

export default Navbar;
