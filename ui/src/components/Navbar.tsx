import { Link, NavLink } from "react-router-dom";
import { useTranslation } from "react-i18next";

import "../assets/css/navbar.css";
import { useAuth } from "../auth/AuthContext";
import { useTheme } from "../hooks/useTheme";
import LanguageSwitcher from "./LanguageSwitcher";

const Navbar = () => {
	const { t } = useTranslation();
	const { theme, toggleTheme } = useTheme();
	const auth = useAuth();

	const canSeeSettings =
		auth.status === "authenticated" &&
		(auth.user.role === "admin" || auth.user.role === "root");

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
								{t("nav.home")}
							</NavLink>
						</li>

						{canSeeSettings && (
							<li className="nav-item">
								<NavLink
									to="/setting"
									className={({ isActive }) =>
										isActive ? "nav-link active" : "nav-link"
									}
								>
									{t("nav.setting")}
								</NavLink>
							</li>
						)}
					</ul>

					<LanguageSwitcher />

					<button
						type="button"
						className="theme-toggle"
						onClick={toggleTheme}
						aria-label={
							theme === "light"
								? t("nav.themeToDark")
								: t("nav.themeToLight")
						}
					>
						{/* Show the theme you would switch to: moon while
						    light, sun while dark. */}
						<i
							className={
								theme === "light"
									? "bi bi-moon-fill"
									: "bi bi-sun-fill"
							}
							aria-hidden="true"
						/>
					</button>
				</div>
			</div>
		</nav>
	);
};

export default Navbar;