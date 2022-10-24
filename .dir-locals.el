;;; Directory Local Variables
;;; For more information see (info "(emacs) Directory Variables")

((python-mode . ((flycheck-checker . python-pylint)
                    (eval . (flycheck-add-next-checker 'python-flake8 '(warning . python-pylint)))
                    (lsp-diagnostics-disabled-modes . (python-mode)))))
